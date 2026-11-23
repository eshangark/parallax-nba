export type ScoredGame = {
  season: string; evidence: string; model_version: string; model_sha256: string | null;
  completed_at: string; home_id: string; away_id: string; eligible: number;
  home_probability: number; away_probability: number; home_win: number;
};

export function scores(rows: ScoredGame[]) {
  if (!rows.length) return { accuracy: null, brier: null, loss: null };
  let correct = 0, error = 0, loss = 0;
  for (const { home_probability: p, home_win: y } of rows) {
    const safe = Math.max(1e-12, Math.min(1 - 1e-12, p));
    correct += Number(Number(p >= .5) === y);
    error += (p - y) ** 2;
    loss -= y * Math.log(safe) + (1-y) * Math.log1p(-safe);
  }
  return { accuracy: correct / rows.length, brier: error / rows.length, loss: loss / rows.length };
}

export function bands(rows: ScoredGame[], team = '') {
  const step = team ? 10 : 5;
  const groups = new Map<number, { n: number; wins: number; sum: number }>();
  for (const row of rows) {
    if (team && row.home_id !== team && row.away_id !== team) continue;
    const home = team ? row.home_id === team : row.home_probability >= .5;
    const p = home ? row.home_probability : row.away_probability;
    const key = Math.min(100 - step, Math.floor(Math.round(p * 100 * 1e8) / 1e8 / step) * step);
    const band = groups.get(key) ?? { n: 0, wins: 0, sum: 0 };
    band.n += 1;
    band.wins += home ? row.home_win : 1 - row.home_win;
    band.sum += p;
    groups.set(key, band);
  }
  return [...groups].sort(([a], [b]) => a - b).map(([key, { n, wins, sum }]) => {
    const rate = wins / n;
    const z = 1.959963984540054;
    const divisor = 1 + z * z / n;
    const center = (rate + z * z / (2 * n)) / divisor;
    const margin = z * Math.sqrt((rate * (1 - rate) + z * z / (4 * n)) / n) / divisor;
    return { label: `${key}–${key + step}%`, n, mean: sum / n, rate,
      low: Math.max(0, center - margin), high: Math.min(1, center + margin) };
  });
}
