"""Build a local relational read model from the authoritative Parallax archives."""

import hashlib
import json
import sqlite3
from datetime import timezone
from pathlib import Path

from .accuracy_data import accuracy_catalog
from .model import EASTERN, timestamp
from .seasons import load_season

STATS = ('points', 'fgm', 'fga', 'threem', 'threea', 'ftm', 'fta', 'oreb', 'dreb',
         'ast', 'stl', 'tov', 'largest_lead')


def utc(value):
    return timestamp(value).astimezone(timezone.utc).isoformat(timespec='microseconds')


def _add_game(db, season, game, status):
    home, away = game['home'], game['away']
    for team in (home, away):
        db.execute('INSERT INTO teams VALUES (?, ?) ON CONFLICT(team_id) DO UPDATE SET name=excluded.name',
                   (team['id'], team['name']))
    final = status == 'final'
    db.execute('INSERT INTO games VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (
        game['game_id'], season, utc(game['start']),
        timestamp(game['start']).astimezone(EASTERN).date().isoformat(),
        home['id'], away['id'], status, home['points'] if final else None,
        away['points'] if final else None, utc(game['last_play_at']) if final else None))
    if final:
        db.executemany('INSERT INTO team_games VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (
            (game['game_id'], side, game[side]['id'], *(game[side][key] for key in STATS))
            for side in ('home', 'away')))


def _add_ledger(db, season, archive, source, completed):
    internal = archive.get('_internal', {})
    awaiting = {row['game_id'] for row in archive.get('awaiting_final', [])}
    known_games = {game['game_id'] for game in completed}
    for game in internal.get('pending', []):
        _add_game(db, season, game, 'awaiting_final' if game['game_id'] in awaiting else 'scheduled')
        known_games.add(game['game_id'])

    revisions = {}
    for row in internal.get('forecasts', []):
        game_id, forecast_id = row['game_id'], row['forecast_id']
        if forecast_id in revisions:
            raise ValueError(f'Duplicate forecast ID: {forecast_id}')
        revisions[forecast_id] = row
        for side in ('home', 'away'):
            db.execute('INSERT OR IGNORE INTO teams VALUES (?, ?)', (row[side + '_id'], row[side]))
        if game_id not in known_games:
            db.execute('INSERT INTO games VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)', (
                game_id, season, utc(row['start']),
                timestamp(row['start']).astimezone(EASTERN).date().isoformat(),
                row['home_id'], row['away_id'], 'archived'))
            known_games.add(game_id)
        db.execute('INSERT INTO issued_forecasts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (
            forecast_id, game_id, row['home_id'], row['away_id'], utc(row['issued_at']),
            utc(row['forecast_cutoff']), utc(row['start']), row['model_version'],
            row.get('forecast_model_sha256'), row.get('parameter_hash'),
            row['home_probability'], row['away_probability'], row.get('base_home_probability'),
            row['eligible_for_evaluation'], row.get('injury_status'),
            json.dumps(row, sort_keys=True, allow_nan=False), source))

    for row in archive.get('upcoming', []):
        game = db.execute('SELECT start, home_id, away_id, status FROM games WHERE game_id = ?',
                          (row['game_id'],)).fetchone()
        if (revisions.get(row['forecast_id']) != row or game is None
                or tuple(game) != (utc(row['start']), row['home_id'], row['away_id'], 'scheduled')):
            raise ValueError(f'Upcoming forecast differs from schedule or ledger: {row["game_id"]}')
        db.execute('INSERT INTO upcoming VALUES (?, ?)', (row['game_id'], row['forecast_id']))

    selected = dict(db.execute('''
        SELECT f.game_id, f.forecast_id FROM latest_issued f JOIN games g USING (game_id)
        WHERE g.season = ?
    ''', (season,)))
    expected = {row['game_id']: row['forecast_id'] for row in archive['result']['predictions']
                if row['kind'] == 'issued_live'}
    if selected != expected:
        raise ValueError(f'{season}: issued forecast selection differs from collector')


def populate(db, root):
    """Create a new database. Roll back inserts on any invalid source or parity failure."""
    archives = root / 'data/seasons'
    paths = sorted(archives.glob('*/*.json')) + sorted(archives.glob('*.json'))
    paths += sorted(archives.glob('*/team_games.csv')) + sorted(archives.glob('*/replay-inputs.json.gz'))
    paths += [root / 'models/nba-v0.3' / name for name in ('bundle.json', 'matched-evaluation.json')]
    hashes = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    entries = json.loads((archives / 'index.json').read_text())['seasons']
    catalog, notices = accuracy_catalog(root, entries)
    replay_seasons = {row['season'] for row in catalog['replay']}
    if any(entry.get('file') and entry['season'] not in replay_seasons for entry in entries):
        raise ValueError('Current-method replay is inconsistent with the archive or model')
    db.execute('PRAGMA foreign_keys = ON')
    db.executescript(Path(__file__).with_name('sql').joinpath('analytics.sql').read_text())
    with db:
        db.executemany('INSERT INTO sources VALUES (?, ?)', hashes.items())
        for entry in sorted(entries, key=lambda item: item['season']):
            season = entry['season']
            archive = load_season(archives, entry)
            if archive is None:
                continue
            source = f'data/seasons/{entry["file"]}'
            if archive.get('status') == 'live':
                status = json.loads((archives / season / 'update_status.json').read_text())
                if (status['state'] != 'success'
                        or utc(status['last_successful_at']) != utc(archive['published_at'])):
                    raise ValueError(f'{season}: live archive has no matching successful collection')
            internal = archive.get('_internal', {})
            games_path = archives / season / 'games.json'
            completed = internal['games'] if 'games' in internal else json.loads(games_path.read_text())
            for game in completed:
                _add_game(db, season, game, 'final')
            _add_ledger(db, season, archive, source, completed)
            rating_result, rating_source = archive['result'], source
            if season in replay_seasons:
                replay_path = archives / season / 'current-model.json'
                rating_result = json.loads(replay_path.read_text())['result']
                rating_source = replay_path.relative_to(root).as_posix()
            for team in rating_result['rankings']:
                db.execute('INSERT OR IGNORE INTO teams VALUES (?, ?)', (team['team_id'], team['team']))
                db.execute('INSERT INTO team_ratings VALUES (?, ?, ?, ?, ?, ?)', (
                    season, team['team_id'], team['elo'], team['games'], team['wins'], rating_source))
            for row in rating_result['predictions']:
                game = db.execute('SELECT home_id, away_id, completed_at FROM games WHERE game_id = ?',
                                  (row['game_id'],)).fetchone()
                for side, team_id in zip(('home', 'away'), game[:2]):
                    elo = row.get(side + '_rating_after')
                    if elo is not None:
                        db.execute('INSERT INTO rating_history VALUES (?, ?, ?, ?, ?, ?)', (
                            season, row['game_id'], team_id, game[2], elo, row.get(side + '_rating_change')))
            for kind, path in (
                ('replay', archives / season / 'current-model.json'),
                ('chronological', archives / season / 'snapshot-v0.3.json'),
            ):
                verified = {row['game_id'] for row in catalog[kind] if row['season'] == season}
                if verified:
                    saved = json.loads(path.read_text())['result']
                    _add_evaluation(db, season, kind, saved, verified, path.relative_to(root).as_posix())
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Analytics database contains a dangling reference')
        verify_inputs(db, root)
    return notices


def _add_evaluation(db, season, kind, result, verified, source):
    evidence = result['evaluation_role'] if kind == 'replay' else 'chronological_backtest'
    run_id = f'{season}:{evidence}'
    rows = result['predictions']
    if {row['game_id'] for row in rows} != verified or len(rows) != len(verified):
        raise ValueError(f'{run_id}: evaluation game set differs from verified catalog')
    # Chronological folds carry their fingerprint on the rows.
    model_hashes = {row.get('forecast_model_sha256') for row in rows}
    versions = {row['model_version'] for row in rows}
    if len(model_hashes) != 1 or len(versions) != 1:
        raise ValueError(f'{run_id}: multiple model identities in one run')
    db.execute('INSERT INTO evaluation_runs VALUES (?, ?, ?, ?, ?, ?)', (
        run_id, season, evidence, versions.pop(), model_hashes.pop(), source))
    db.executemany('INSERT INTO evaluation_predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (
        (run_id, row['game_id'], row['home_probability'], row['away_probability'],
         utc(row['forecast_cutoff']), utc(row['start']), row['eligible_for_evaluation'],
         row.get('injury_status')) for row in rows))



def verify_inputs(db, root):
    """Reject a mixed snapshot if the collector writes while a release is built."""
    for path, fingerprint in db.execute('SELECT path, sha256 FROM sources'):
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != fingerprint:
            raise ValueError(f'Input changed during analytics build: {path}')
