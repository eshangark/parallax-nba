"""Generate allowlisted website and BI data from the SQLite read model."""

import csv
import hashlib
import json
import sqlite3
from collections import defaultdict
from bisect import bisect_left
from itertools import accumulate

from . import __version__
from .evaluation import favorite_bands
from .forecasting import Forecaster
from .model import timestamp
from .replay import metrics
from .reliability import injury_details
from .dashboard_data import probability_steps

SCHEMA_VERSION = 3


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True) + '\n',
                    encoding='utf-8')


def _player_observations(internal):
    boxes = internal.get('player_games', {})
    observed = internal.get('first_observed_at', {})
    history = defaultdict(list)
    for game in sorted(internal.get('games', ()), key=lambda g: (timestamp(g['last_play_at']), g['game_id'])):
        game_id = game['game_id']
        completed = timestamp(game['last_play_at'])
        first_seen = timestamp(observed[game_id]) if game_id in observed else completed
        for team in boxes.get(game_id, {}).values():
            for player in team or ():
                history[player['athlete']].append((completed, first_seen, player['minutes'], player.get('points')))
    return history


def _injury_players(record, internal, observations):
    cutoff = timestamp(record['forecast_cutoff'])
    seed = (internal.get('initialization', {}).get('feature_seed') or {}).get('player_history', {})
    reports = record.get('injury_report') or {}
    decay = 2**(-1/10)
    rows = []
    for side in ('away', 'home'):
        report = reports.get(record[side + '_id'])
        if not report or not report['submitted']:
            continue
        for player in report['players']:
            athlete = player.get('athlete')
            minutes, games, _ = seed.get(athlete, (0., 0., 0.))
            points = []
            for completed, first_seen, played, scored in observations.get(athlete, ()):
                if completed < cutoff and first_seen <= cutoff:
                    minutes, games = decay*minutes + played, decay*games + 1
                    if scored is not None:
                        points.append(scored)
            rows.append({
                'team': record[side], 'name': player['name'], 'status': player['status'],
                'matched': athlete is not None,
                'expected_minutes': minutes / games if games else None,
                'points_per_game': sum(points) / len(points) if points else None,
            })
    return rows


def _forecast(row, internal, observations):
    record = json.loads(row['record_json'])
    return {
        'evidence': 'issued',
        'forecast_id': row['forecast_id'],
        'issued_at': row['issued_at'],
        'cutoff': row['cutoff'],
        'captured_start': row['captured_start'],
        'model_version': row['model_version'],
        'model_sha256': row['model_sha256'],
        'issued_model_version': row['issued_model_version'],
        'issued_model_sha256': row['issued_model_sha256'],
        'home_probability': row['home_probability'],
        'away_probability': row['away_probability'],
        'base_home_probability': row['base_home_probability'],
        'injury_status': row['injury_status'],
        'injury_coverage': {side: (record.get('injury_coverage') or {}).get(side)
                            for side in ('home', 'away')},
        'injury_report_at': (record.get('injury_source') or {}).get('published_at'),
        'schedule_projected': bool(record.get('scheduled_context_projected')),
        'probability_steps': probability_steps(record, internal.get('parameter_registry', {})
                                               .get(record.get('parameter_hash'), {}).get('parameters', {})),
        'injury_details': [
            {key: detail[key] for key in ('Team', 'Report', 'Unmatched names', 'Missing histories')}
            for detail in injury_details(record)['teams']
        ],
        'injury_players': _injury_players(record, internal, observations),
        'context': {side: {
            'elo': record.get(side + '_rating'),
            'rest_days': (record.get(side + '_context') or {}).get('rest'),
            'travel_km': (record.get(side + '_context') or {}).get('travel'),
        } for side in ('home', 'away')},
    }


def export(db, root, target):
    """Write one coherent, deterministic export into a new staging directory."""
    db.row_factory = sqlite3.Row
    internals = {path.parent.name: json.loads(path.read_text())['_internal']
                 for path in (root / 'data/seasons').glob('*/live.json')}
    observations = {season: _player_observations(internal) for season, internal in internals.items()}
    model = Forecaster(json.loads((root / 'models/nba-v1.0/bundle.json').read_text()))
    fingerprint = model.fingerprint
    selected = {}
    compatible = sorted(model.compatible_fingerprints)
    placeholders = ",".join("?" for _ in compatible)
    for row in db.execute(f'''
        WITH revisions AS (
            SELECT f.*, g.season, row_number() OVER (
                PARTITION BY f.game_id ORDER BY f.issued_at DESC, f.forecast_id
            ) AS revision
            FROM issued_forecasts f JOIN games g USING (game_id)
            LEFT JOIN upcoming u ON u.forecast_id = f.forecast_id
            WHERE f.model_sha256 IN ({placeholders}) AND f.home_id = g.home_id AND f.away_id = g.away_id
                AND f.issued_at < g.start
                AND (g.status IN ('final', 'awaiting_final')
                     OR (g.status = 'scheduled' AND u.forecast_id IS NOT NULL))
        )
        SELECT * FROM revisions WHERE revision = 1
    ''', compatible):
        row = dict(row)
        row.update(issued_model_version=row['model_version'], issued_model_sha256=row['model_sha256'],
                   model_version=model.bundle['version'], model_sha256=fingerprint)
        selected[row['game_id']] = row

    groups = defaultdict(list)
    evaluation = []
    for game in db.execute("SELECT * FROM games WHERE status = 'final' ORDER BY season, game_id"):
        row = selected.get(game['game_id'])
        if row is None:
            continue
        data = {key: row[key] for key in ('forecast_id', 'game_id', 'season', 'model_version', 'model_sha256',
                 'issued_model_version', 'issued_model_sha256',
                 'home_probability', 'away_probability', 'cutoff', 'captured_start', 'eligible', 'injury_status')}
        data.update(evidence='issued', home_win=int(game['home_score'] > game['away_score']),
                    completed_at=game['completed_at'], home_id=game['home_id'], away_id=game['away_id'])
        evaluation.append(data)
        groups[(row['season'], 'issued', row['model_version'], fingerprint)].append(data)

    forecasts_by_season = defaultdict(list)
    for row in selected.values():
        forecasts_by_season[row['season']].append({
            key: row[key] for key in (
                'forecast_id', 'game_id', 'season', 'issued_at', 'cutoff', 'captured_start',
                'home_id', 'away_id', 'model_version', 'model_sha256',
                'issued_model_version', 'issued_model_sha256',
                'home_probability', 'away_probability', 'injury_status')
        })
    for season, rows in sorted(forecasts_by_season.items()):
        _write(target / 'downloads' / f'{season}-saved-forecasts.json',
               sorted(rows, key=lambda row: (row['issued_at'], row['game_id'])))
    _write(target / 'model.json', {
        'version': model.bundle['version'], 'sha256': fingerprint,
        'core_parameters': model.bundle['core_parameters'],
    })
    _write(target / 'scored-games.json', evaluation)
    historical = [dict(row) for row in db.execute('''
        SELECT e.game_id, e.season, e.evidence, e.model_version, e.model_sha256,
               e.home_probability, e.away_probability, e.cutoff, e.captured_start, e.eligible,
               e.injury_status, e.home_win, g.completed_at, g.home_id, g.away_id
        FROM evaluation_rows e JOIN games g USING (game_id)
        WHERE e.evidence = 'training_replay' AND e.model_sha256 = ? AND g.status = 'final'
        ORDER BY g.season, g.game_id
    ''', (fingerprint,))]
    _write(target / 'historical-accuracy.json', historical)
    form = defaultdict(list)
    for row in db.execute("SELECT * FROM games WHERE status = 'final' ORDER BY completed_at, game_id"):
        for side, opponent in (('home', 'away'), ('away', 'home')):
            form[(row['season'], row[side + '_id'])].append(
                (row['completed_at'], row[side + '_score'] > row[opponent + '_score']))
    form = {key: ([item[0] for item in values], list(accumulate((item[1] for item in values), initial=0)))
            for key, values in form.items()}
    slates = defaultdict(list)
    finals = defaultdict(int)
    for row in db.execute('SELECT * FROM game_slate ORDER BY start, game_id'):
        if not row['game_id'].isascii() or not row['game_id'].isdigit():
            raise ValueError(f'Unsafe game identifier for release path: {row["game_id"]!r}')
        game = dict(row)
        game.pop('forecast_id')
        selected_row = selected.get(row['game_id'])
        forecast = (_forecast(selected_row, internals[row['season']], observations[row['season']])
                    if selected_row is not None else None)
        if row['status'] == 'final':
            finals[row['season']] += 1
        if forecast:
            for side in ('away', 'home'):
                dates, wins = form.get((row['season'], row[side + '_id']), ([], [0]))
                count = bisect_left(dates, forecast['cutoff'])
                recent = max(0, count - 10)
                forecast['context'][side].update(prior_games=count, recent_wins=wins[count] - wins[recent],
                                                 recent_games=count - recent)
        game['forecast'] = forecast
        summary = {**game, 'forecast': (
            {key: forecast[key] for key in ('home_probability', 'away_probability', 'issued_at',
                                            'injury_status', 'forecast_id', 'cutoff')} if forecast else None)}
        slates[row['slate_date']].append(summary)
        _write(target / 'games' / f'{row["game_id"]}.json',
               game)

    for date, games in slates.items():
        _write(target / 'slates' / f'{date}.json', games)
    for season, in db.execute('SELECT DISTINCT season FROM ranked_teams ORDER BY season'):
        teams = [dict(row) for row in db.execute('''
            SELECT team_id, name, elo, elo_rank, games, wins
            FROM ranked_teams WHERE season = ? ORDER BY elo_rank, team_id
        ''', (season,))]
        history = defaultdict(list)
        for row in db.execute('''
            SELECT team_id, game_id, effective_at, elo, change
            FROM rating_history WHERE season = ? ORDER BY effective_at, game_id
        ''', (season,)):
            item = dict(row)
            history[item.pop('team_id')].append(item)
        for team in teams:
            team['history'] = history[team['team_id']]
        _write(target / 'teams' / f'{season}.json', teams)

    scorecards = []
    for (season, evidence, version, fingerprint), rows in groups.items():
        scorecards.append({
            'season': season, 'evidence': evidence, 'model_version': version,
            'model_sha256': fingerprint,
            'all_games': metrics(rows), 'established': metrics([row for row in rows if row['eligible']]),
            'favorite_calibration': favorite_bands(rows),
        })
    _write(target / 'evaluation.json', {
        'scorecards': scorecards,
        'issued_coverage': {season: {'completed': count,
                                     'issued': sum(len(rows) for key, rows in groups.items()
                                                   if key[:2] == (season, 'issued'))}
                            for season, count in finals.items()
                            if (root / 'data/seasons' / season / 'live.json').exists()},
    })
    _export_calibration(target.parent / 'bi' / 'calibration.csv', groups)
    _export_scores(target.parent / 'bi' / 'scores.csv', groups)

    checks = {}
    for path in sorted((root / 'data/seasons').glob('*/update_status.json')):
        status = json.loads(path.read_text())
        checks[path.parent.name] = {key: status.get(key) for key in (
            'state', 'attempted_at', 'last_successful_at')}
    inputs = dict(db.execute('SELECT path, sha256 FROM sources ORDER BY path'))
    inventory = {path.relative_to(target).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in sorted(target.rglob('*')) if path.is_file()}
    _write(target / 'integrity.json', inventory)
    _write(target / 'manifest.json', {
        'schema_version': SCHEMA_VERSION, 'application_version': __version__,
        'model_version': model.bundle['version'], 'model_sha256': fingerprint,
        'source_sha256': hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
        'dates': sorted(slates), 'seasons': sorted(finals.keys() | checks.keys()),
        'latest_snapshot_at': max((value['last_successful_at'] for value in checks.values()
                                   if value['last_successful_at']), default=None),
        'collection': checks,
        'integrity_sha256': hashlib.sha256((target / 'integrity.json').read_bytes()).hexdigest(),
    })


def _export_calibration(path, groups):
    """Write additive statistics so BI filters can recombine bands correctly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(('season', 'evidence', 'model_version', 'model_sha256', 'injury_status',
                         'band', 'games', 'favorite_wins', 'sum_favorite_probability'))
        for (season, evidence, version, fingerprint), rows in groups.items():
            by_injury = defaultdict(list)
            for row in rows:
                by_injury[row['injury_status'] or 'unknown'].append(row)
            for injury, records in sorted(by_injury.items()):
                for band in favorite_bands(records):
                    writer.writerow((season, evidence, version, fingerprint, injury, band['band'],
                                     band['games'], band['wins'], band['mean_forecast'] * band['games']))


def _export_scores(path, groups):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(('season', 'evidence', 'model_version', 'model_sha256', 'injury_status',
                         'established', 'games', 'correct', 'sum_brier', 'sum_log_loss'))
        for key, rows in groups.items():
            segments = defaultdict(list)
            for row in rows:
                segments[(row['injury_status'] or 'unknown', row['eligible'])].append(row)
            for (injury, established), records in sorted(segments.items()):
                score = metrics(records)
                n = score['games']
                writer.writerow((*key, injury, established, n, round(score['winner_accuracy'] * n),
                                 score['brier_score'] * n, score['log_loss'] * n))
