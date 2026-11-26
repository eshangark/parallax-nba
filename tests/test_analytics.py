from collections import Counter
import csv
import hashlib
import json
import sqlite3
from shutil import copytree
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from nba_forecast.analytics import populate, utc
from nba_forecast.analytics_exports import _injury_players, _player_observations
from nba_forecast.replay import metrics
from nba_forecast.forecasting import Forecaster
from scripts.build_analytics import build

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / 'data/seasons/2026-27/live.json'


class AnalyticsTests(unittest.TestCase):
    def test_injury_player_statistics_use_only_observed_pregame_boxes(self):
        cutoff = '2026-11-25T20:00:00Z'
        record = {
            'forecast_cutoff': cutoff, 'home': 'Knicks', 'away': 'Cavs',
            'home_id': '18', 'away_id': '5',
            'injury_report': {'18': {'submitted': True, 'players': [
                {'athlete': '1', 'name': 'Matched Player', 'status': 'Questionable'},
                {'athlete': None, 'name': 'Unmatched Player', 'status': 'Out'},
                {'athlete': '2', 'name': 'Player with Legacy History', 'status': 'Available'},
            ]}, '5': {'submitted': False, 'players': []}},
        }
        internal = {
            'games': [
                {'game_id': '1', 'last_play_at': '2026-11-23T20:00:00Z'},
                {'game_id': '2', 'last_play_at': '2026-11-24T20:00:00Z'},
                {'game_id': '3', 'last_play_at': cutoff},
            ],
            'first_observed_at': {'1': cutoff, '2': '2026-11-25T21:00:00Z'},
            'player_games': {
                '1': {'18': [{'athlete': '1', 'minutes': 30, 'points': 0},
                             {'athlete': '2', 'minutes': 12}]},
                '2': {'18': [{'athlete': '1', 'minutes': 45, 'points': 40}]},
                '3': {'18': [{'athlete': '1', 'minutes': 40, 'points': 35}]},
            },
            'initialization': {'features': {'player_history': {'1': [20, 1, 0]}}},
        }
        rows = _injury_players(record, internal, _player_observations(internal))
        self.assertEqual(len(rows), 3)
        decay = 2**(-1/10)
        self.assertAlmostEqual(rows[0]['expected_minutes'], (20*decay + 30)/(decay + 1))
        self.assertEqual(rows[0]['points_per_game'], 0)
        self.assertEqual(rows[0]['status'], 'Questionable')
        self.assertFalse(rows[1]['matched'])
        self.assertIsNone(rows[1]['expected_minutes'])
        self.assertIsNone(rows[1]['points_per_game'])
        self.assertEqual(rows[2]['expected_minutes'], 12)
        self.assertIsNone(rows[2]['points_per_game'])

    def test_sql_counts_forecast_identity_and_canonical_metrics(self):
        live = json.loads(LIVE.read_text())
        with closing(sqlite3.connect(':memory:')) as db:
            populate(db, ROOT)
            self.assertEqual(db.execute("""
                SELECT count(*) FROM team_games JOIN games USING (game_id)
                WHERE season < '2026-27'
            """).fetchone()[0], 12300)
            expected = {row['forecast_id']: row for row in live['_internal']['forecasts']}
            self.assertEqual({key: json.loads(row) for key, row in db.execute(
                'SELECT forecast_id, record_json FROM issued_forecasts')}, expected)
            selected = {row['game_id']: row['forecast_id'] for row in live['result']['predictions']
                        if row['kind'] == 'issued_live'}
            self.assertEqual(dict(db.execute('SELECT game_id, forecast_id FROM latest_issued')), selected)
            self.assertEqual(db.execute("SELECT count(*) FROM evaluation_rows "
                                        "WHERE evidence = 'chronological_backtest'").fetchone()[0], 3690)
            db.row_factory = sqlite3.Row
            rows = list(db.execute("SELECT * FROM evaluation_rows WHERE evidence = 'issued'"))
            for key in ('games', 'log_loss', 'brier_score', 'winner_accuracy'):
                self.assertAlmostEqual(metrics(rows)[key], live['result']['metrics_all_issued'][key], places=12)

    def test_deterministic_allowlisted_release(self):
        with TemporaryDirectory() as directory:
            first, second = (Path(directory) / name for name in ('first', 'second'))
            build(ROOT, first)
            build(ROOT, second)
            manifest = json.loads((first / 'site/manifest.json').read_text())
            self.assertEqual((first / 'site/manifest.json').read_bytes(),
                             (second / 'site/manifest.json').read_bytes())
            self.assertEqual((first / 'bi/calibration.csv').read_bytes(),
                             (second / 'bi/calibration.csv').read_bytes())
            inventory = (first / 'site/integrity.json').read_bytes()
            self.assertEqual(hashlib.sha256(inventory).hexdigest(), manifest['integrity_sha256'])
            for name, digest in json.loads(inventory).items():
                payload = (first / 'site' / name).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), digest)
                self.assertNotIn(b'"_internal"', payload)
                self.assertNotIn(b'"forecast_features"', payload)
                self.assertNotIn(b'"record_json"', payload)
                self.assertFalse(name.endswith('-team_games.csv'))
                if name.startswith('games/'):
                    forecast = json.loads(payload)['forecast']
                    if forecast:
                        self.assertNotIn('players', forecast)
                        self.assertNotIn('player_impact', forecast)
                        for player in forecast['injury_players']:
                            self.assertEqual(set(player), {
                                'team', 'name', 'status', 'matched', 'expected_minutes', 'points_per_game',
                            })
                        for team in forecast['injury_details']:
                            self.assertNotIn('Unresolved availability', team)
            live = json.loads(LIVE.read_text())
            for item in live['awaiting_final']:
                game = json.loads((first / 'site/games' / f'{item["game_id"]}.json').read_text())
                self.assertEqual(game['status'], 'awaiting_final')
                candidates = [row for row in live['_internal']['forecasts']
                              if row['game_id'] == item['game_id'] and utc(row['issued_at']) < game['start']
                              and row['home_id'] == game['home_id'] and row['away_id'] == game['away_id']]
                if any(row.get('forecast_model_sha256') == manifest['model_sha256'] for row in candidates):
                    self.assertIsNotNone(game['forecast'])
            with (first / 'bi/calibration.csv').open(newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual({row['model_sha256'] for row in rows}, {manifest['model_sha256']})
            self.assertEqual({row['evidence'] for row in rows}, {'issued'})
            scored = json.loads((first / 'site/scored-games.json').read_text())
            self.assertEqual({row['model_sha256'] for row in scored}, {manifest['model_sha256']})
            self.assertEqual({row['evidence'] for row in scored}, {'issued'})
            self.assertEqual({row['model_version'] for row in scored}, {'1.0.0'})
            current = Forecaster(json.loads((ROOT/'models/nba-v1.0/bundle.json').read_text()))
            expected = {row['forecast_id'] for row in live['result']['predictions']
                        if row.get('forecast_model_sha256') in current.compatible_fingerprints}
            self.assertEqual({row['forecast_id'] for row in scored}, expected)
            with closing(sqlite3.connect(first / 'parallax.sqlite3')) as db:
                raw = dict(db.execute('SELECT forecast_id, record_json FROM issued_forecasts'))
            for row in scored:
                original = json.loads(raw[row['forecast_id']])
                self.assertEqual(row['issued_model_version'], original['model_version'])
                self.assertEqual(row['issued_model_sha256'], original['forecast_model_sha256'])
                self.assertEqual(row['home_probability'], original['home_probability'])
            historical = json.loads((first / 'site/historical-accuracy.json').read_text())
            self.assertEqual(Counter(row['season'] for row in historical),
                             {f'{year}-{str(year + 1)[-2:]}': 1230 for year in range(2021, 2026)})
            self.assertEqual({row['evidence'] for row in historical}, {'training_replay'})
            self.assertEqual({row['model_sha256'] for row in historical}, {manifest['model_sha256']})
            ids = [row['game_id'] for row in scored + historical]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(all(row['cutoff'] < row['captured_start'] <= row['completed_at'] for row in historical))
            self.assertEqual(len(scored), len({row['game_id'] for row in scored}))
            issued = json.loads((first / 'site/downloads/2026-27-saved-forecasts.json').read_text())
            self.assertEqual(len(issued), len({row['game_id'] for row in issued}))
            saved_ids = {row['game_id']: row['forecast_id'] for row in issued}
            scored_ids = {row['game_id']: row['forecast_id'] for row in scored}
            for path in (first / 'site/games').glob('*.json'):
                game = json.loads(path.read_text())
                self.assertNotIn('replay', game)
                if game['forecast']:
                    forecast = game['forecast']
                    self.assertEqual(forecast['model_sha256'], manifest['model_sha256'])
                    if game['season'] == '2026-27':
                        self.assertEqual(forecast['forecast_id'], saved_ids[game['game_id']])
                    if game['status'] == 'final':
                        self.assertEqual(forecast['forecast_id'], scored_ids[game['game_id']])
            with self.assertRaises(FileExistsError):
                build(ROOT, first)

    def test_partial_collector_write_cannot_be_published(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'data/seasons'
            copytree(ROOT / 'data/seasons', archive)
            (root / 'models').symlink_to(ROOT / 'models', target_is_directory=True)
            current = archive / '2026-27'
            status = json.loads((LIVE.parent / 'update_status.json').read_text())
            status['state'] = 'failed'
            (current / 'update_status.json').write_text(json.dumps(status))
            output = root / 'incomplete'
            with self.assertRaisesRegex(ValueError, 'no matching successful collection'):
                build(root, output)
            self.assertFalse(output.exists())

    def test_export_failure_preserves_previous_release(self):
        with TemporaryDirectory() as directory:
            previous = Path(directory) / 'previous'
            previous.mkdir()
            marker = previous / 'manifest.json'
            marker.write_text('last good')
            output = Path(directory) / 'next'
            with patch('scripts.build_analytics.export', side_effect=RuntimeError('interrupted')):
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    build(ROOT, output)
            self.assertEqual(marker.read_text(), 'last good')
            self.assertEqual(list(Path(directory).iterdir()), [previous])
