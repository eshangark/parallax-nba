# Parallax NBA web dashboard

Use a supported Node.js 24 release and pnpm. Run these commands from `web/`.

```sh
pnpm install --frozen-lockfile
ASTRO_TELEMETRY_DISABLED=1 pnpm build
ASTRO_TELEMETRY_DISABLED=1 pnpm preview --host 127.0.0.1 --port 4321
```

Open http://127.0.0.1:4321/parallax-nba/. The build reads `../local/refresh/current/site` by default. Regenerate older exports to use schema v3. Set `PARALLAX_DATA_DIR` to an absolute path to another validated analytics export. After refreshing the backend, rebuild the static site to display the new snapshot. Astro serves date and matchup routes under `/parallax-nba/`.

To run the browser tests after building, run `pnpm exec playwright install chromium` and then `ASTRO_TELEMETRY_DISABLED=1 pnpm test`. Set `PARALLAX_BROWSER` to the executable path to use an installed Chromium-based browser. Tests use a real local analytics export with upcoming, completed and missing-data records.

The local preview includes Today, dated Matchup pages, the game archive, team ratings and history, forecast accuracy, methodology and downloads. Rebuild the analytics export before building this interface. The expanded pages use the scored-game and matchup detail fields added to the export. See the analytics documentation for the Pages pipeline and its deployment switch.

To add an approved walkthrough to Home, set `PUBLIC_PARALLAX_DEMO_VIDEO` at build time. Set `PUBLIC_PARALLAX_DEMO_CAPTIONS` to its WebVTT URL and `PUBLIC_PARALLAX_DEMO_POSTER` to a poster image URL if available. Use URLs under the project base path for assets served with the site.
