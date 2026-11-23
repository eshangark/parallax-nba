import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.refresh_analytics import refresh


class RefreshTests(unittest.TestCase):
    def test_current_changes_only_after_successful_build(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / 'output'
            output.mkdir()
            old = output / 'old'
            old.mkdir()
            current = output / 'current'
            current.symlink_to('old')
            args = (root, output, root / 'cities.zip', root / 'cache')

            def successful_build(_root, release):
                self.assertEqual(current.resolve(), old)
                release.mkdir(parents=True)
                return []

            with patch('scripts.refresh_analytics.run_update') as collect:
                with patch('scripts.refresh_analytics.build', side_effect=ValueError('invalid archive')):
                    with self.assertRaisesRegex(ValueError, 'invalid archive'):
                        refresh(*args)
                self.assertEqual(current.resolve(), old)
                with patch('scripts.refresh_analytics.build', side_effect=successful_build):
                    release, _ = refresh(*args)
                self.assertEqual(collect.call_count, 2)
            self.assertEqual(current.resolve(), release)
            self.assertTrue(old.is_dir())
