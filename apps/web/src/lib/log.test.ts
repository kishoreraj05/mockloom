import { describe, expect, it } from 'vitest';
import type { LogEntry } from '@/api/client';
import { matchesFilter, mergeRows } from './log';

const row = (id: string, extra = {}) =>
  ({ id, method: 'GET', path: `/p/${id}`, status: 200, rule_name: null, ...extra }) as LogEntry;

describe('mergeRows', () => {
  it('appends in order and ignores rows it already has', () => {
    const merged = mergeRows([row('a')], [row('a'), row('b')]);
    expect(merged.map((r) => r.id)).toEqual(['a', 'b']);
  });

  it('keeps the same array when nothing is new, so React can skip a render', () => {
    const existing = [row('a')];
    expect(mergeRows(existing, [row('a')])).toBe(existing);
    expect(mergeRows(existing, [])).toBe(existing);
  });

  it('puts rows recovered after a reconnect back in time order', () => {
    const live = row('live', { ts: '2026-01-01T00:00:05+00:00' });
    const recovered = row('gap', { ts: '2026-01-01T00:00:03Z' });
    expect(mergeRows([live], [recovered]).map((r) => r.id)).toEqual(['gap', 'live']);
  });

  it('drops the oldest rows past the cap', () => {
    expect(mergeRows([row('a'), row('b')], [row('c')], 2).map((r) => r.id)).toEqual(['b', 'c']);
  });
});

describe('matchesFilter', () => {
  it('searches method, path, status and rule name', () => {
    const entry = row('x', { status: 404, rule_name: 'Empty Cart' });
    for (const needle of ['get', '/P/X', '404', 'empty cart', '  ']) expect(matchesFilter(entry, needle)).toBe(true);
    expect(matchesFilter(entry, 'post')).toBe(false);
  });
});
