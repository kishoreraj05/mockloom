import { ArrowLeft, Flame, ListTree, ScrollText, FileCode2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useRoutes, useUpdateWorkspace, useWorkspace } from '@/api/hooks';
import { CopyButton } from '@/components/CopyButton';
import { Button } from '@/components/ui/button';
import { Input, Label } from '@/components/ui/fields';
import { Switch } from '@/components/ui/switch';
import { ChaosBoard } from '@/features/chaos/ChaosBoard';
import { EndpointExplorer } from '@/features/endpoints/EndpointExplorer';
import { EndpointPane } from '@/features/endpoints/EndpointPane';
import { RequestLog } from '@/features/log/RequestLog';
import { SpecEditor } from '@/features/spec/SpecEditor';
import { emptyDraft } from '@/lib/rules';
import { cn, mockBaseUrl } from '@/lib/utils';
import { useUi } from '@/store/ui';

type View = 'endpoints' | 'spec' | 'chaos';
/** On narrow screens the three panes become one at a time. */
type Pane = 'list' | 'main' | 'log';

function Settings({ slug }: { slug: string }) {
  const workspace = useWorkspace(slug).data;
  const update = useUpdateWorkspace(slug);
  const toast = useUi((state) => state.toast);
  const [seed, setSeed] = useState('');
  useEffect(() => {
    if (workspace) setSeed(String(workspace.seed));
  }, [workspace]);
  if (!workspace) return null;
  const onError = (error: Error) => toast(error.message, 'bad');
  return (
    <div className="flex items-center gap-3 text-xs">
      <label className="flex items-center gap-1.5 text-muted" title="Reject requests that break the spec with a 400">
        Validate requests
        <Switch
          label="Validate requests"
          checked={workspace.validation_mode === 'strict'}
          onCheckedChange={(on) => update.mutate({ validation_mode: on ? 'strict' : 'off' }, { onError })}
        />
      </label>
      <div className="flex items-center gap-1.5" title="The same seed always generates the same data">
        <Label htmlFor="seed" className="mb-0 normal-case tracking-normal text-xs font-normal">
          Seed
        </Label>
        <Input
          id="seed"
          value={seed}
          inputMode="numeric"
          className="h-7 w-16 font-mono text-xs"
          onChange={(event) => setSeed(event.target.value)}
          onBlur={() => {
            const next = Number(seed);
            if (Number.isInteger(next) && next !== workspace.seed) update.mutate({ seed: next }, { onError });
            else setSeed(String(workspace.seed));
          }}
        />
      </div>
    </div>
  );
}

export function WorkspacePage() {
  const { slug = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const workspace = useWorkspace(slug);
  const routes = useRoutes(slug);
  const search = useRef<HTMLInputElement>(null);
  const logFilter = useRef<HTMLInputElement>(null);
  const [pane, setPane] = useState<Pane>('main');
  const { setDraft, setTab } = useUi.getState();

  const view = (params.get('view') as View) || 'endpoints';
  const routeKey = params.get('route');

  const select = (key: string | null, nextView: View = 'endpoints') => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (key) next.set('route', key);
        else next.delete('route');
        next.set('view', nextView);
        return next;
      },
      { replace: true },
    );
    setPane('main');
  };

  // Land on a useful screen: the spec editor when there is no spec, else the first route.
  useEffect(() => {
    if (!routes.data || !workspace.data) return;
    if (routes.data.length === 0 && !params.get('view')) select(null, 'spec');
    else if (!routeKey && view === 'endpoints' && routes.data.length) select(routes.data[0].key);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routes.data, workspace.data]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement;
      const typing = target.closest('input, textarea, select, [contenteditable], .monaco-editor');
      if (typing || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === '/') {
        event.preventDefault();
        setPane('list');
        search.current?.focus();
      } else if (event.key === 'l') {
        event.preventDefault();
        setPane('log');
        logFilter.current?.focus();
      } else if (event.key === 'n' && routeKey) {
        event.preventDefault();
        select(routeKey);
        setTab('rules');
        setDraft(emptyDraft(routeKey));
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeKey]);

  // Each workspace has its own log and draft.
  useEffect(() => {
    useUi.getState().clearLogRows();
    useUi.getState().setDraft(null);
  }, [slug]);

  if (workspace.isError) {
    return (
      <main className="mx-auto max-w-md px-4 py-16 text-center">
        <p className="font-medium">{workspace.error.message}</p>
        <Link to="/" className="mt-2 inline-block text-accent underline">
          Back to workspaces
        </Link>
      </main>
    );
  }

  const url = workspace.data ? mockBaseUrl(workspace.data.mock_path) : '';
  const viewButton = (value: View, label: string, Icon: typeof Flame) => (
    <Button
      size="sm"
      variant="ghost"
      aria-pressed={view === value}
      className={cn(view === value && 'bg-raised text-ink')}
      onClick={() => select(routeKey, value)}
    >
      <Icon size={13} /> {label}
    </Button>
  );

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-surface px-3 py-1.5">
        <Link to="/" aria-label="All workspaces" className="text-muted hover:text-ink">
          <ArrowLeft size={15} />
        </Link>
        <h1 className="max-w-48 truncate font-semibold">{workspace.data?.name ?? '…'}</h1>
        <div className="flex min-w-0 items-center rounded border border-line bg-raised pl-2">
          <code data-testid="mock-url" className="truncate font-mono text-xs text-muted">{url}</code>
          <CopyButton text={url} label="Copy mock URL" />
        </div>
        <nav className="flex items-center gap-0.5" aria-label="Workspace views">
          {viewButton('endpoints', 'Endpoints', ListTree)}
          {viewButton('spec', 'Spec', FileCode2)}
          {viewButton('chaos', 'Chaos', Flame)}
        </nav>
        <div className="ml-auto hidden md:block">
          <Settings slug={slug} />
        </div>
      </header>

      <nav className="flex border-b border-line bg-surface lg:hidden" aria-label="Panes">
        {(
          [
            ['list', 'Routes', ListTree],
            ['main', 'Editor', FileCode2],
            ['log', 'Log', ScrollText],
          ] as const
        ).map(([value, label, Icon]) => (
          <button
            key={value}
            aria-pressed={pane === value}
            onClick={() => setPane(value)}
            className={cn(
              'flex flex-1 items-center justify-center gap-1 py-1.5 text-xs text-muted',
              pane === value && 'border-b-2 border-accent font-medium text-ink',
            )}
          >
            <Icon size={13} /> {label}
          </button>
        ))}
      </nav>

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[260px_minmax(0,1fr)_minmax(340px,34%)]">
        <aside className={cn('min-h-0 border-r border-line bg-surface', pane === 'list' ? 'block' : 'hidden lg:block')}>
          <EndpointExplorer slug={slug} selected={routeKey} onSelect={(key) => select(key)} searchRef={search} />
        </aside>
        <main className={cn('min-h-0 overflow-hidden', pane === 'main' ? 'block' : 'hidden lg:block')}>
          {view === 'spec' && <SpecEditor slug={slug} />}
          {view === 'chaos' && <ChaosBoard slug={slug} />}
          {view === 'endpoints' &&
            (routeKey ? (
              <EndpointPane slug={slug} routeKey={routeKey} />
            ) : (
              <div className="grid h-full place-items-center text-muted">Choose a route on the left.</div>
            ))}
        </main>
        <aside className={cn('min-h-0 border-l border-line bg-surface', pane === 'log' ? 'block' : 'hidden lg:block')}>
          <RequestLog
            slug={slug}
            filterRef={logFilter}
            onCreateRule={(key) => {
              select(key);
              setTab('rules');
            }}
          />
        </aside>
      </div>
    </div>
  );
}
