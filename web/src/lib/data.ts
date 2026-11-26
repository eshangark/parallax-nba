import type { ScoredGame } from './accuracy';
import { createHash } from 'node:crypto';
import { readFileSync, realpathSync } from 'node:fs';
import { join } from 'node:path';
import { dayKey, shiftDay } from './slate';

type Context = { elo: number | null; rest_days: number | null; travel_km: number | null; prior_games: number; recent_wins: number; recent_games: number };
export type Forecast = {
  forecast_id: string; home_probability: number; away_probability: number;
  issued_at: string; cutoff: string; injury_status: string | null;
};
export type Game = {
  game_id: string; season: string; slate_date: string; start: string;
  home: string; away: string; home_id: string; away_id: string;
  home_score: number | null; away_score: number | null;
  status: 'scheduled' | 'awaiting_final' | 'final'; forecast: Forecast | null;
};
export type Matchup = Omit<Game, 'forecast'> & {
  forecast: (Forecast & {
  model_version: string; model_sha256: string; base_home_probability: number | null;
  injury_coverage: Record<'home' | 'away', string | null>;
  injury_report_at: string | null; schedule_projected: boolean;
  probability_steps: { Stage: string; 'Home win %': number; 'Change (pp)': number | null }[];
  injury_details: { Team: string; Report: string; 'Unmatched names': number | null; 'Missing histories': number | null }[];
  injury_players: { team: string; name: string; status: string; matched: boolean;
    expected_minutes: number | null; points_per_game: number | null }[];
  context: Record<'home' | 'away', Context>;
}) | null };

const source = realpathSync(process.env.PARALLAX_DATA_DIR ||
  '../local/refresh/current/site');
const bytes = (path: string) => readFileSync(join(source, path));
const sha256 = (payload: Buffer) => createHash('sha256').update(payload).digest('hex');
export const manifest = JSON.parse(bytes('manifest.json').toString('utf8')) as {
  schema_version: number; seasons: string[]; dates: string[]; latest_snapshot_at: string | null;
  model_version: string; model_sha256: string; integrity_sha256: string;
  collection: Record<string, { state: string; attempted_at: string; last_successful_at: string }>;
};
if (manifest.schema_version !== 3) throw new Error('Unsupported Parallax export schema');
const integrity = bytes('integrity.json');
if (sha256(integrity) !== manifest.integrity_sha256) throw new Error('Parallax export inventory mismatch');
const inventory = JSON.parse(integrity.toString('utf8')) as Record<string, string>;

export function readAsset(path: string): Buffer {
  if (!Object.hasOwn(inventory, path)) throw new Error(`Unlisted Parallax asset: ${path}`);
  const payload = bytes(path);
  if (sha256(payload) !== inventory[path]) throw new Error(`Parallax export checksum mismatch: ${path}`);
  return payload;
}
export function read<T>(path: string): T {
  return JSON.parse(readAsset(path).toString('utf8')) as T;
}
export const downloadNames = Object.keys(inventory).filter(path => path.startsWith('downloads/'))
  .map(path => path.slice('downloads/'.length));
export const today = dayKey();
const available = new Set(manifest.dates);
export const slateDays = [...new Set([
  ...manifest.dates,
  ...Array.from({ length: 15 }, (_, index) => shiftDay(today, index - 7)),
])].sort();
export const slate = (day: string) => available.has(day) ? read<Game[]>(`slates/${day}.json`) : [];
export const matchup = (id: string) => read<Matchup>(`games/${id}.json`);
export const games = () => manifest.dates.flatMap(slate);

export type Team = { team_id: string; name: string; elo: number; elo_rank: number; wins: number; games: number;
  history: { game_id: string; effective_at: string; elo: number; change: number | null }[] };
const teamCache = new Map<string, Team[]>();
export function teams(season: string) {
  if (!teamCache.has(season)) teamCache.set(season, read<Team[]>(`teams/${season}.json`));
  return teamCache.get(season)!;
}
export const seasonLabel = (season: string) => season.replace('-', '–');

let scored: ScoredGame[] | undefined;
export const scoredGames = () => scored ??= read<ScoredGame[]>('scored-games.json').filter(row => row.evidence === 'issued');
export const historicalAccuracy = () => read<ScoredGame[]>('historical-accuracy.json');
