# Local analytics backend

Build a release from a fixed, complete source snapshot using Python 3.12 and SQLite 3.37 or newer.

```sh
python scripts/audit_comparisons.py
python scripts/build_analytics.py --output local/releases/example
python -m unittest discover -s tests -v
```

Choose a new output directory for each build. The command stages the database and exports together and exposes the directory only after all work succeeds. Inputs remain in the existing season archives and frozen model files. The analytics builder runs offline. A failed collection or inconsistent replay inventory blocks release generation. The previous complete release remains available.

## Outputs

| Path | Use |
|---|---|
| `parallax.sqlite3` | Local SQL exploration and release generation. Contains source hashes and original issued forecast payloads. |
| `site/manifest.json` | Export schema v3, application and model versions, active bundle fingerprint, input fingerprint, dates, collection status, and integrity inventory fingerprint. |
| `site/integrity.json` | File hashes for release verification. The Astro build verifies each exported asset it reads. |
| `site/slates/<date>.json` | Summary records ordered by scheduled tip and grouped by Eastern date. |
| `site/games/<game-id>.json` | Matchup, outcome, active model’s latest eligible pregame forecast, where available. |
| `site/teams/<season>.json` | Season ranks and rating history. Every season uses the verified active-model replay. |
| `site/downloads/` | One selected pregame forecast per game. |
| `site/evaluation.json` | Scorecards grouped by season, evidence and model, with issued coverage and calibration. |
| `bi/calibration.csv` | Additive counts and probability sums by favorite band and report coverage. |
| `bi/scores.csv` | Additive score totals by season, evidence, model, coverage and eligibility. |

Current-season game-history Elo changes measure the completed game’s update, including league recentering, against the rating immediately before that update. They exclude intervening games since an early forecast was issued. Dated slate headings remain valid after midnight; the Today navigation still routes to the current Eastern date.

The SQL window in `latest_issued` applies the collector's issued-record selection. `evaluation_rows` joins evidence to outcomes and keeps training replays, post-fit replays, chronological backtests and original forecasts labeled. The canonical Python metrics determine calibration and scores. The website and BI exports use only the frozen bundle fingerprint. Active original forecasts are selected after filtering the immutable ledger to that fingerprint. The exported site and BI scores use the same selected issued records. Historical replays and forecast revisions remain in the local database for research and audit. Archive keeps the final score for games without a saved forecast.

Export fields are explicit. Publish a reviewed subset of `site/` or BI data when hosting and source reuse are settled. Keep the generated database and development materials local.

## Refresh from live providers

```sh
python scripts/download_geography.py
python scripts/refresh_analytics.py --cities data/raw/geography/cities15000.zip
```

The refresh holds the collector lock across collection, SQLite validation, export and the switch to a new release. Open `local/refresh/current/site/manifest.json` or `local/refresh/current/parallax.sqlite3` to inspect the latest successful release. Releases are stored in separate directories, and the current pointer switches atomically. A failed collection or build leaves that pointer in place. The source archive remains authoritative for preserving issued records and may advance before an analytics build succeeds. Rerun refresh to retry, or use the offline builder to inspect a successfully collected archive independently.

The refresh command runs on demand and is suitable for a later scheduler integration.

## Hosting and recovery

The release workflow builds pull requests and checks the static site in Chromium. On the two-hour schedule or a manual dispatch from main, it collects new records, saves the ledger, then builds from the exact resulting commit. A code push builds from its own source commit. Pages is gated by the `PARALLAX_PAGES_ENABLED` repository variable and a Pages environment configured to deploy through GitHub Actions. Leave the variable unset until data and media publication are approved and a dry run succeeds. The public release metadata is available at `release.json`.

A collection or validation failure keeps the last Pages release in service. A collection can save a valid live ledger before a downstream replay write fails. Retain that ledger, inspect the failed check and rerun against current main. Restore the site by rebuilding a reviewed code revision against current compatible source data. Preserve issued records throughout rollback.
