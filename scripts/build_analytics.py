"""Build a local SQLite database and release exports without contacting providers."""

import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nba_forecast.analytics import populate, verify_inputs
from nba_forecast.analytics_exports import export


def build(root, output):
    if output.exists() or output.is_symlink():
        raise FileExistsError(f'Choose a new output directory: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(mkdtemp(prefix='.analytics-', dir=output.parent))
    try:
        with closing(sqlite3.connect(stage / 'parallax.sqlite3')) as db:
            notices = populate(db, root)
            export(db, root, stage / 'site')
            verify_inputs(db, root)
        stage.rename(output)
    finally:
        if stage.exists():
            rmtree(stage)
    return notices


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New release directory')
    args = parser.parse_args()
    notices = build(ROOT, args.output.absolute())
    for notice in notices:
        print(notice)
    print(f'Built analytics release at {args.output}')
