import type { LogEntry } from '@/api/client';

export const MAX_ROWS = 10_000;

/** Merge new rows into a log, dropping duplicates and the oldest rows past the cap. */
export function mergeRows(existing: LogEntry[], incoming: LogEntry[], max = MAX_ROWS): LogEntry[] {
  if (incoming.length === 0) return existing;
  const seen = new Set(existing.map((row) => row.id));
  const fresh = incoming.filter((row) => !seen.has(row.id));
  if (fresh.length === 0) return existing;
  const merged = [...existing, ...fresh];
  // Rows recovered after a reconnect can be older than rows that already arrived live.
  const newest = existing.length ? Date.parse(existing[existing.length - 1].ts) : -Infinity;
  if (fresh.some((row) => Date.parse(row.ts) < newest)) {
    merged.sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts));
  }
  return merged.length > max ? merged.slice(merged.length - max) : merged;
}

export function matchesFilter(row: LogEntry, filter: string): boolean {
  const needle = filter.trim().toLowerCase();
  if (!needle) return true;
  return [row.method, row.path, String(row.status), row.rule_name ?? ''].some((field) =>
    field.toLowerCase().includes(needle),
  );
}
