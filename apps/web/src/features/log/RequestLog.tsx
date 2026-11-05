import { useQueryClient } from '@tanstack/react-query';
import { useVirtualizer } from '@tanstack/react-virtual';
import { ArrowDown, Trash2, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import { api, type LogEntry, unwrap } from '@/api/client';
import { MethodBadge } from '@/components/MethodBadge';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/fields';
import { matchesFilter, MAX_ROWS } from '@/lib/log';
import { draftFromLog } from '@/lib/rules';
import { cn, formatClock, prettyJson, statusTone } from '@/lib/utils';
import { useUi } from '@/store/ui';

const ROW_HEIGHT = 26;
const FLUSH_MS = 60;
const PAGE_SIZE = 1000;

function useLogStream(slug: string) {
  const addRows = useUi((state) => state.addLogRows);
  const setConnection = useUi((state) => state.setConnection);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry: number | undefined;
    let attempts = 0;
    let closed = false;

    // Coalesces a burst into one render. A timer, not requestAnimationFrame, because that stops
    // in background tabs, which is where this page often is while an app is being tested.
    let buffer: LogEntry[] = [];
    let timer: number | undefined;
    const flush = () => {
      timer = undefined;
      addRows(buffer);
      buffer = [];
    };

    function connect() {
      setConnection('connecting');
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
      socket = new WebSocket(`${scheme}://${window.location.host}/api/workspaces/${slug}/logs/stream`);
      socket.onopen = () => {
        attempts = 0;
        setConnection('live');
        // Anything that happened while disconnected; the store drops duplicates.
        unwrap(api.GET('/api/workspaces/{slug}/logs', { params: { path: { slug } } }))
          .then((rows) => addRows(rows))
          .catch(() => undefined);
      };
      socket.onmessage = (event) => {
        buffer.push(...(JSON.parse(event.data) as LogEntry[]));
        timer ??= window.setTimeout(flush, FLUSH_MS);
      };
      socket.onclose = () => {
        if (closed) return;
        setConnection('offline');
        attempts += 1;
        retry = window.setTimeout(connect, Math.min(1000 * 2 ** attempts, 15_000));
      };
    }

    connect();
    return () => {
      closed = true;
      window.clearTimeout(retry);
      window.clearTimeout(timer);
      socket?.close();
    };
  }, [slug, addRows, setConnection]);
}

function Pre({ label, text }: { label: string; text: string | null | undefined }) {
  return (
    <div>
      <h5 className="mb-0.5 text-2xs font-medium uppercase tracking-wide text-muted">{label}</h5>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded bg-raised p-2 font-mono text-2xs">
        {text ? prettyJson(text) : <span className="text-muted">None</span>}
      </pre>
    </div>
  );
}

function headerText(headers: unknown): string {
  return Object.entries((headers ?? {}) as Record<string, string>)
    .map(([name, value]) => `${name}: ${value}`)
    .join('\n');
}

function Detail({ entry, onClose, onCreateRule }: { entry: LogEntry; onClose: () => void; onCreateRule: () => void }) {
  const request = entry.request as { headers?: unknown; body?: string | null };
  const response = entry.response as { headers?: unknown; body?: string | null; notes?: string[] };
  return (
    <section className="flex max-h-[60%] min-h-0 flex-col border-t border-line bg-surface" aria-label="Request details">
      <div className="flex items-center gap-1 border-b border-line px-2 py-1">
        <MethodBadge method={entry.method} />
        <span className="min-w-0 flex-1 truncate font-mono text-xs" title={entry.path}>{entry.path}</span>
        <Button size="sm" onClick={onCreateRule} disabled={!entry.route_key}>
          Create rule from this request
        </Button>
        <Button size="icon" variant="ghost" aria-label="Close details" onClick={onClose}>
          <X size={13} />
        </Button>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2">
        <p className="text-xs">
          <span className={cn('font-mono font-semibold', statusTone(entry.status))}>
            {entry.status === 0 ? 'dropped' : entry.status}
          </span>
          <span className="text-muted">
            {' '}in {entry.duration_ms.toFixed(1)} ms ({entry.overhead_ms.toFixed(2)} ms overhead), from {entry.source}
          </span>
          {entry.rule_name && <> · Rule: <span className="font-medium">{entry.rule_name}</span></>}
          {entry.chaos.length > 0 && <span className="text-accent"> · Chaos: {entry.chaos.join(', ')}</span>}
        </p>
        {response.notes?.map((note) => (
          <p key={note} className="text-xs text-warn">{note}</p>
        ))}
        <Pre label="Response body" text={response.body} />
        <Pre label="Request body" text={request.body} />
        <Pre label="Request headers" text={headerText(request.headers)} />
        <Pre label="Response headers" text={headerText(response.headers)} />
      </div>
    </section>
  );
}

export function RequestLog({
  slug,
  filterRef,
  onCreateRule,
}: {
  slug: string;
  filterRef: RefObject<HTMLInputElement>;
  onCreateRule: (routeKey: string) => void;
}) {
  useLogStream(slug);
  const rows = useUi((state) => state.logRows);
  const connection = useUi((state) => state.connection);
  const selectedId = useUi((state) => state.selectedLogId);
  const select = useUi((state) => state.selectLog);
  const clearRows = useUi((state) => state.clearLogRows);
  const addRows = useUi((state) => state.addLogRows);
  const setDraft = useUi((state) => state.setDraft);
  const toast = useUi((state) => state.toast);
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [following, setFollowing] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [reachedStart, setReachedStart] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);

  const visible = useMemo(() => rows.filter((row) => matchesFilter(row, filter)), [rows, filter]);
  const virtual = useVirtualizer({
    count: visible.length,
    getScrollElement: () => scroller.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });

  // Stick to the newest row, unless the reader has scrolled up to look at something.
  useEffect(() => {
    if (following && visible.length) virtual.scrollToIndex(visible.length - 1, { align: 'end' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible.length, following]);

  const selected = selectedId ? rows.find((row) => row.id === selectedId) : undefined;

  async function loadOlder() {
    setLoadingOlder(true);
    setFollowing(false);
    try {
      const page = await unwrap(
        api.GET('/api/workspaces/{slug}/logs', {
          params: { path: { slug }, query: { before: rows[0].ts, limit: PAGE_SIZE } },
        }),
      );
      addRows(page);
      if (page.length < PAGE_SIZE) setReachedStart(true);
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : 'Could not load older requests.', 'bad');
    } finally {
      setLoadingOlder(false);
    }
  }

  async function clearLog() {
    try {
      await unwrap(api.DELETE('/api/workspaces/{slug}/logs', { params: { path: { slug } } }));
      clearRows();
      setReachedStart(false);
      void queryClient.invalidateQueries({ queryKey: ['workspaces', slug] });
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : 'Could not clear the log.', 'bad');
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1.5 border-b border-line p-2">
        <span
          className={cn(
            'h-2 w-2 shrink-0 rounded-full',
            connection === 'live' ? 'bg-ok' : connection === 'connecting' ? 'bg-warn' : 'bg-bad',
          )}
          role="img"
          aria-label={`Log stream ${connection}`}
          title={`Log stream ${connection}`}
        />
        <h2 className="shrink-0 font-medium">Requests</h2>
        <div className="relative min-w-0 flex-1">
          <Input
            ref={filterRef}
            value={filter}
            aria-label="Filter requests"
            placeholder="Filter"
            className="h-7 pr-6 text-xs"
            onChange={(event) => setFilter(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                setFilter('');
                event.currentTarget.blur();
              }
            }}
          />
          <kbd className="absolute right-2 top-1/2 -translate-y-1/2">l</kbd>
        </div>
        <span className="shrink-0 font-mono text-2xs text-muted">{visible.length}</span>
        <Button size="icon" variant="ghost" aria-label="Clear log" disabled={rows.length === 0} onClick={() => setConfirming(true)}>
          <Trash2 size={13} />
        </Button>
      </div>

      <div className="relative min-h-0 flex-1">
        <div
          ref={scroller}
          data-testid="log-rows"
          className="h-full overflow-y-auto"
          onScroll={(event) => {
            const element = event.currentTarget;
            setFollowing(element.scrollHeight - element.scrollTop - element.clientHeight < ROW_HEIGHT * 2);
          }}
        >
          {rows.length >= PAGE_SIZE && rows.length < MAX_ROWS && !reachedStart && (
            <div className="border-b border-line p-1 text-center">
              <Button size="sm" variant="ghost" disabled={loadingOlder} onClick={() => void loadOlder()}>
                {loadingOlder ? 'Loading…' : 'Load older requests'}
              </Button>
            </div>
          )}
          {visible.length === 0 && (
            <p className="p-4 text-center text-muted">
              {rows.length ? 'No requests match this filter.' : 'Waiting for requests. Call the mock URL, or use Try it.'}
            </p>
          )}
          <ul style={{ height: virtual.getTotalSize(), position: 'relative' }} aria-label="Request log">
            {virtual.getVirtualItems().map((item) => {
              const row = visible[item.index];
              return (
                <li
                  key={row.id}
                  style={{ position: 'absolute', top: 0, left: 0, right: 0, height: ROW_HEIGHT, transform: `translateY(${item.start}px)` }}
                >
                  <button
                    aria-current={row.id === selectedId ? 'true' : undefined}
                    className={cn(
                      'flex h-full w-full items-center gap-1.5 border-b border-line px-2 text-left text-xs hover:bg-raised',
                      // Only truly new rows flash: virtualised rows remount whenever they scroll back in.
                      Date.now() - Date.parse(row.ts) < 1000 && 'row-new',
                      row.id === selectedId && 'bg-accent-soft hover:bg-accent-soft',
                    )}
                    onClick={() => select(row.id === selectedId ? null : row.id)}
                  >
                    <span className="hidden shrink-0 font-mono text-2xs text-muted xl:inline">{formatClock(row.ts)}</span>
                    <MethodBadge method={row.method} />
                    <span className="min-w-0 flex-1 truncate font-mono text-2xs" title={row.path}>{row.path}</span>
                    {row.rule_name && (
                      <span className="max-w-24 shrink-0 truncate rounded bg-accent-soft px-1 text-2xs" title={`Rule: ${row.rule_name}`}>
                        {row.rule_name}
                      </span>
                    )}
                    <span className={cn('w-7 shrink-0 text-right font-mono font-medium', statusTone(row.status))}>
                      {row.status === 0 ? 'drop' : row.status}
                    </span>
                    <span className="w-12 shrink-0 text-right font-mono text-2xs text-muted">{Math.round(row.duration_ms)} ms</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
        {!following && visible.length > 0 && (
          <Button
            size="sm"
            className="absolute bottom-2 left-1/2 -translate-x-1/2 shadow"
            onClick={() => setFollowing(true)}
          >
            <ArrowDown size={13} /> Jump to latest
          </Button>
        )}
      </div>

      {selected && (
        <Detail
          entry={selected}
          onClose={() => select(null)}
          onCreateRule={() => {
            setDraft(draftFromLog(selected));
            onCreateRule(selected.route_key!);
          }}
        />
      )}

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Clear the request log?"
        description="This deletes every logged request in this workspace."
        confirmLabel="Clear log"
        onConfirm={() => void clearLog()}
      />
    </div>
  );
}
