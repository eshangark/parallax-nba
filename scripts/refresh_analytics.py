"""Collect NBA data and switch the local analytics release after a successful build."""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nba_forecast.live import live_lock
from nba_forecast.model import EASTERN
from nba_forecast.seasons import current_season
from scripts.build_analytics import build
from scripts.update_live import run_update


def refresh(root, output, cities, cache, horizon_days=7, full_refresh=False):
    archives = root / 'data/seasons'
    current = output / 'current'
    args = argparse.Namespace(
        archives=archives, cities=cities, cache=cache, legacy=False,
        bundle=root / 'models/nba-v0.3/bundle.json',
        horizon_days=horizon_days, full_refresh=full_refresh,
    )
    with live_lock(archives):
        if current.exists() and not current.is_symlink():
            raise FileExistsError(f'Release pointer must be a symlink: {current}')
        started = datetime.now(timezone.utc)
        season = current_season(started.astimezone(EASTERN).date())
        run_update(args, started, season)
        release = output / 'releases' / f'{started:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}'
        notices = build(root, release)
        with TemporaryDirectory(prefix='.switch-', dir=output) as directory:
            pointer = Path(directory) / 'current'
            pointer.symlink_to(release.relative_to(output), target_is_directory=True)
            os.replace(pointer, current)
    return release, notices


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cities', required=True, type=Path)
    parser.add_argument('--cache', type=Path, default=ROOT / 'data/raw/live-espn')
    parser.add_argument('--output', type=Path, default=ROOT / 'local/refresh')
    parser.add_argument('--horizon-days', type=int, default=7, choices=range(1, 15))
    parser.add_argument('--full-refresh', action='store_true')
    args = parser.parse_args()
    release, notices = refresh(ROOT, args.output, args.cities, args.cache,
                               args.horizon_days, args.full_refresh)
    for notice in notices:
        print(notice)
    print(f'Current local release: {release}')
