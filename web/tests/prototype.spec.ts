import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { bands, type ScoredGame } from '../src/lib/accuracy';

const root = '/parallax-nba/';
const data = resolve(process.env.PARALLAX_DATA_DIR || '../local/refresh/current/site');
const manifest = JSON.parse(readFileSync(resolve(data, 'manifest.json'), 'utf8'));
const readSlate = (date: string) => JSON.parse(readFileSync(resolve(data, 'slates', date + '.json'), 'utf8'));

test('mobile slate, stale status and shareable matchup', async ({ page }) => {
  const date = [...manifest.dates].reverse().find(day =>
    readSlate(day).some(game => game.status === 'scheduled' && game.forecast));
  const game = readSlate(date).find(game => game.status === 'scheduled' && game.forecast);
  await page.setViewportSize({ width: 320, height: 760 });
  await page.clock.setFixedTime(new Date(Date.parse(manifest.latest_snapshot_at) + 7 * 3600_000));
  await page.goto(root + 'slate/' + date + '/');
  await expect(page.getByRole('heading', { name: 'Matchups' })).toBeVisible();
  await expect(page.locator('.game-card time').first()).toBeVisible();
  await expect(page.getByText('Stale data')).toBeVisible();
  expect(await page.locator('body').evaluate(body => body.scrollWidth)).toBeLessThanOrEqual(320);
  await page.locator(`a[href="${root}games/${game.game_id}/"]`).click();
  await expect(page).toHaveURL(new RegExp(`/games/${game.game_id}/$`));
  await expect(page.getByRole('heading', { name: 'Pregame forecast' })).toBeVisible();
  await page.getByText('Why this forecast?', { exact: true }).click();
  await expect(page.getByText('Elo rating').first()).toBeVisible();
  await expect(page.getByText('Estimated travel').first()).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: game.away + ' at ' + game.home })).toBeVisible();
  expect(await page.locator('body').evaluate(body => body.scrollWidth)).toBeLessThanOrEqual(320);
  await page.getByRole('link', { name: 'Back to slate' }).click();
  await expect(page.getByRole('heading', { name: 'Matchups' })).toBeVisible();
});

test('finished games preserve the outcome and flag missing pregame forecasts', async ({ page }) => {
  const historical: ScoredGame[] = JSON.parse(readFileSync(resolve(data, 'historical-accuracy.json'), 'utf8'));
  const replayIds = new Set(historical.map(row => row.game_id));
  const finished = manifest.dates.flatMap(readSlate).filter(game => game.status === 'final' && !game.forecast);
  const game = finished.find(game => replayIds.has(game.game_id));
  await page.goto(root + 'games/' + game.game_id + '/');
  await expect(page.getByRole('heading', { name: 'Final score' })).toBeVisible();
  await expect(page.getByText('No live pregame forecast is on record for this game.', { exact: true })).toBeVisible();
  await expect(page.getByText('includes a historical replay for this game.')).toBeVisible();
  await page.getByRole('link', { name: 'Forecast Accuracy', exact: true }).click();
  await expect(page.getByText('Live forecasts were saved before tipoff.', { exact: false })).toBeVisible();
  const withoutReplay = finished.find(game => !replayIds.has(game.game_id));
  await page.goto(root + 'games/' + withoutReplay.game_id + '/');
  await expect(page.getByText('No live pregame forecast is on record for this game.', { exact: true })).toBeVisible();
  await expect(page.getByText('includes a historical replay for this game.')).toHaveCount(0);
});

test('missing injury reports are explicit', async ({ page }) => {
  const game = manifest.dates.flatMap(readSlate).find(game => game.forecast?.injury_status === 'elo_fallback');
  await page.goto(root + 'games/' + game.game_id + '/');
  await expect(page.locator('[aria-labelledby=forecast-heading]').getByText('Elo only · report unavailable', { exact: false })).toBeVisible();
});

test('Today links and built assets resolve under the project path', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 850 });
  const failures: string[] = [];
  page.on('response', response => { if (response.status() >= 400) failures.push(response.url()); });
  await page.goto(root);
  await expect(page.getByRole('heading', { level: 1, name: 'Parallax NBA' })).toBeVisible();
  await page.getByRole('link', { name: 'Today', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'NBA slate' })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  expect(failures).toEqual([]);
});

test('Home serves the walkthrough and English captions', async ({ page }) => {
  await page.goto(root);
  await expect(page.getByRole('heading', { name: 'Dashboard walkthrough' })).toBeVisible();
  const video = page.locator('video[controls]');
  const src = await video.getAttribute('src');
  expect(src).toMatch(/^\/parallax-nba\/demo\/.*\.mp4$/);
  const metadata = await page.request.get(src!, { headers: { Range: 'bytes=0-31' } });
  expect(metadata.status()).toBe(206);
  expect(metadata.headers()['content-type']).toContain('video/mp4');
  expect((await metadata.body()).subarray(4, 8).toString()).toBe('ftyp');
  const track = video.locator('track[kind=captions][srclang=en]');
  await expect(track).not.toHaveAttribute('default', /.*/);
  const response = await page.request.get((await track.getAttribute('src'))!);
  expect(response.ok()).toBeTruthy();
  expect(await response.text()).toMatch(/^WEBVTT/);
});

test('archive defaults to completed games and can show scheduled games', async ({ page }) => {
  const upcoming = manifest.dates.flatMap(readSlate).find(game => game.status === 'scheduled');
  await page.setViewportSize({ width: 320, height: 760 });
  await page.goto(root + 'archive/');
  const status = page.getByLabel('Game status');
  const records = page.locator('#archive-results li');
  await expect(status).toHaveValue('final');
  await expect(records).toHaveCount(24);
  await expect(records.filter({ hasText: / · Final \d+–\d+ · / })).toHaveCount(24);
  await page.getByRole('button', { name: 'Show more games' }).click();
  await expect(records.filter({ hasText: / · Final \d+–\d+ · / })).toHaveCount(48);
  await page.getByLabel('Date').fill(upcoming.slate_date);
  const scheduled = page.locator(`#archive-results a[href="${root}games/${upcoming.game_id}/"]`);
  await expect(scheduled).toHaveCount(0);
  await status.selectOption('all');
  await expect(scheduled).toContainText('Scheduled');
  expect(await page.locator('body').evaluate(body => body.scrollWidth)).toBeLessThanOrEqual(320);
});

test('archive filters historical games and accuracy covers all seasons with labeled sources', async ({ page }) => {
  const date = '2025-11-01';
  await page.goto(root + 'archive/');
  await page.getByLabel('Season').selectOption('2025-26');
  await page.getByLabel('Date').fill(date);
  await expect(page.locator('#archive-results li')).toHaveCount(readSlate(date).length);
  await page.goto(root + 'accuracy/');
  const issued = JSON.parse(readFileSync(resolve(data, 'scored-games.json'), 'utf8'));
  const historical = JSON.parse(readFileSync(resolve(data, 'historical-accuracy.json'), 'utf8'));
  const count = page.locator('#accuracy-metrics strong').first();
  const match = page.locator('#calibration-match-value');
  const expectedMatch = (rows: ScoredGame[], team = '') => {
    const agreement = bands(rows, team).reduce((sum, band) =>
      sum + band.n * (1 - Math.abs(band.mean - band.rate)), 0);
    return `${(100 * agreement / rows.length).toFixed(1)}%`;
  };
  await expect(count).toHaveText(String(6150 + issued.length));
  await expect(page.locator('#season-scores tr')).toHaveCount(6);
  for (const season of manifest.seasons) {
    await page.getByLabel('Season').selectOption(season);
    const live = issued.filter(row => row.season === season).length;
    const replay = historical.filter(row => row.season === season).length;
    await expect(count).toHaveText(String(live + replay));
    await expect(page.locator('#calibration-chart li').first()).toBeVisible();
  }
  await page.getByLabel('Season').selectOption('2025-26');
  await expect(count).toHaveText('1230');
  await expect(page.locator('#accuracy-evidence')).toContainText('1230 historical training replays');
  await page.locator('#accuracy-team').selectOption({ label: 'Los Angeles Lakers' });
  await expect(count).toHaveText('82');
  const team = await page.locator('#accuracy-team').inputValue();
  const teamRows = historical.filter((row: ScoredGame) =>
    row.season === '2025-26' && [row.home_id, row.away_id].includes(team));
  await expect(match).toHaveText(expectedMatch(teamRows, team));
  await page.locator('#accuracy-team').selectOption('');
  await page.getByLabel('Sample').selectOption('established');
  await expect(count).toHaveText(String(historical.filter(row => row.season === '2025-26' && row.eligible).length));
  await page.getByLabel('Sample').selectOption('');
  await page.getByLabel('Forecast source').selectOption('issued');
  await expect(count).toHaveText('0');
  await expect(match).toHaveText('—');
  await expect(page.getByText('No forecasts match these filters.')).toBeVisible();
  await page.getByLabel('Season').selectOption('');
  await expect(count).toHaveText(String(issued.length));
  await expect(match).toHaveText(expectedMatch(issued));
});

test('team history and methodology downloads open from navigation', async ({ page }) => {
  await page.goto(root);
  await page.getByRole('link', { name: 'Teams', exact: true }).click();
  await page.locator('section[data-team-season]:visible tbody a').first().click();
  await expect(page.getByRole('heading', { name: 'Game history' })).toBeVisible();
  expect(await page.locator('tbody tr td:last-child').allTextContents()).not.toContain('—');
  await page.getByRole('link', { name: 'Methodology', exact: true }).click();
  const path = await page.getByRole('link', { name: 'Technical paper' }).getAttribute('href');
  const response = await page.request.get(path!);
  expect(response.ok()).toBeTruthy();
  expect((await response.body()).subarray(0, 4).toString()).toBe('%PDF');
  await page.getByText('Season data downloads', { exact: true }).click();
  const history = await page.getByRole('link', { name: 'Saved pregame forecasts' }).getAttribute('href');
  const issued = await (await page.request.get(history!)).json();
  expect([...new Set(issued.map(row => row.model_sha256))]).toEqual([manifest.model_sha256]);
  expect((await page.request.get(root + 'downloads/matched-evaluation.json')).status()).toBe(404);
});

test('contract calculator compares entered price with the saved probability', async ({ page }) => {
  const game = manifest.dates.flatMap(readSlate).find(game => game.status === 'scheduled' && game.forecast);
  await page.goto(root + 'slate/' + game.slate_date + '/');
  await page.getByRole('link', { name: 'Compare contract price for ' + game.away + ' at ' + game.home }).click();
  await expect(page).toHaveURL(/#contract-pricing$/);
  await page.getByLabel('Buy price in cents').fill('60');
  await expect(page.locator('[data-result=breakEven]')).toHaveText('60%');
  await expect(page.locator('[data-result=win]')).toHaveText('+40.0¢');
  await expect(page.locator('[data-result=loss]')).toHaveText('−60.0¢');
  await page.getByLabel('Team', { exact: true }).selectOption({ label: game.home });
  const gap = game.forecast.home_probability * 100 - 60;
  const magnitude = (Math.round(Math.abs(gap) * 10) / 10).toFixed(1);
  const sign = magnitude === '0.0' ? '' : gap > 0 ? '+' : '−';
  await expect(page.locator('[data-result=expected]')).toHaveText(sign + magnitude + '¢');
  await page.getByLabel('Buy price in cents').fill('101');
  await expect(page.locator('#price-result')).toBeHidden();
});

test('slate headings stay dated after Eastern midnight', async ({ page }) => {
  const day = new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/New_York' }).format(new Date());
  await page.clock.setFixedTime(new Date(Date.parse(day + 'T12:00:00Z') + 24 * 3600_000));
  await page.goto(root + 'slate/' + day + '/');
  await expect(page.getByRole('heading', { level: 1, name: 'NBA slate' })).toBeVisible();
  await expect(page).not.toHaveTitle(/^Today/);
  const date = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
    .format(new Date(day + 'T12:00:00Z'));
  await expect(page).toHaveTitle(date + ' | Parallax NBA');
});
