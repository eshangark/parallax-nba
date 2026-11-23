export const eastern = 'America/New_York';

export const dayKey = (date = new Date()) =>
  new Intl.DateTimeFormat('sv-SE', { timeZone: eastern }).format(date);

export const formatDate = (day: string, options: Intl.DateTimeFormatOptions) =>
  new Intl.DateTimeFormat('en-US', { ...options, timeZone: 'UTC' }).format(new Date(day + 'T12:00:00Z'));

export const clock = (value: string) =>
  new Intl.DateTimeFormat('en-US', { timeZone: eastern, hour: 'numeric', minute: '2-digit' }).format(new Date(value));

export const stamp = (value: string) =>
  new Intl.DateTimeFormat('en-US', {
    timeZone: eastern, month: 'short', day: 'numeric', hour: 'numeric',
    minute: '2-digit', timeZoneName: 'short',
  }).format(new Date(value));

export function shiftDay(day: string, offset: number) {
  const date = new Date(day + 'T12:00:00Z');
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
}

export const pct = (value: number) => Math.round(value * 100) + '%';

export function coverage(status: string | null | undefined) {
  return ({
    complete: 'Both reports submitted',
    partial_or_unsubmitted: 'Reports incomplete',
    elo_fallback: 'Elo only · report unavailable',
  } as Record<string, string>)[status ?? ''] ?? 'Coverage unavailable';
}

export function statusLabel(status: string, start: string) {
  if (status === 'final') return 'Final';
  if (status === 'awaiting_final') return 'Awaiting result';
  return Date.parse(start) <= Date.now() ? 'Scheduled tip passed' : clock(start) + ' ET';
}
