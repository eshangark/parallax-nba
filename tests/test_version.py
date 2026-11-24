"""Keep the public release label and built package on the same version."""
from pathlib import Path
import re
import json
import tomllib
import unittest

from nba_forecast import __version__


class ReleaseVersionTests(unittest.TestCase):
    def test_public_release_and_package_metadata_are_synchronized(self):
        root = Path(__file__).resolve().parents[1]
        metadata = tomllib.loads((root/'pyproject.toml').read_text())
        self.assertIn('version', metadata['project']['dynamic'])
        self.assertEqual(metadata['tool']['setuptools']['dynamic']['version']['attr'], 'nba_forecast.__version__')
        release = re.search(r'Application release: v([0-9]+\.[0-9]+\.[0-9]+)', (root/'README.md').read_text())
        self.assertIsNotNone(release)
        self.assertEqual(release.group(1), __version__)

    def test_production_model_is_identified_in_readme(self):
        root = Path(__file__).resolve().parents[1]
        model = json.loads((root/'models/nba-v1.0/bundle.json').read_text())
        self.assertEqual(model['version'], '1.0.0')
        self.assertIn(f"v{model['version']} forecasting model", (root/'README.md').read_text())
