import { AlertTriangle, Flame, Search } from 'lucide-react';
import { useMemo, useState, type RefObject } from 'react';
import type { RouteSummary } from '@/api/client';
import { useRoutes, useRules } from '@/api/hooks';
import { MethodBadge } from '@/components/MethodBadge';
import { Input } from '@/components/ui/fields';
import { draftFromRule } from '@/lib/rules';
import { cn, plural } from '@/lib/utils';
import { useUi } from '@/store/ui';

function RouteRow({ route, active, onSelect }: { route: RouteSummary; active: boolean; onSelect: () => void }) {
  return (
    <li>
      <button
        onClick={onSelect}
        aria-current={active ? 'true' : undefined}
        title={route.summary || route.path}
        className={cn(
          'flex w-full items-center gap-1 px-3 py-1 text-left hover:bg-raised',
          active && 'bg-accent-soft hover:bg-accent-soft',
        )}
      >
        <MethodBadge method={route.method} />
        <span className="min-w-0 flex-1 truncate font-mono text-xs">{route.path}</span>
        {route.has_chaos && <Flame size={11} className="shrink-0 text-accent" aria-label="Has chaos settings" />}
        {route.rule_count > 0 && (
          <span
            className="shrink-0 rounded-full bg-raised px-1.5 text-2xs text-muted"
            aria-label={plural(route.rule_count, 'rule')}
          >
            {route.rule_count}
          </span>
        )}
      </button>
    </li>
  );
}

export function EndpointExplorer({
  slug,
  selected,
  onSelect,
  searchRef,
}: {
  slug: string;
  selected: string | null;
  onSelect: (key: string) => void;
  searchRef: RefObject<HTMLInputElement>;
}) {
  const routes = useRoutes(slug);
  const rules = useRules(slug);
  const [query, setQuery] = useState('');
  const setDraft = useUi((state) => state.setDraft);

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matching = (routes.data ?? []).filter((route) =>
      `${route.method} ${route.path} ${route.summary}`.toLowerCase().includes(needle),
    );
    const byTag = new Map<string, RouteSummary[]>();
    for (const route of matching) {
      byTag.set(route.tag, [...(byTag.get(route.tag) ?? []), route]);
    }
    return [...byTag.entries()];
  }, [routes.data, query]);

  const orphans = rules.data?.filter((rule) => rule.orphaned) ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="relative border-b border-line p-2">
        <Search size={13} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-muted" />
        <Input
          ref={searchRef}
          value={query}
          aria-label="Search routes"
          placeholder="Search routes"
          className="h-7 pl-7 pr-7 text-xs"
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              setQuery('');
              event.currentTarget.blur();
            }
            if (event.key === 'Enter' && groups[0]?.[1][0]) onSelect(groups[0][1][0].key);
          }}
        />
        <kbd className="absolute right-4 top-1/2 -translate-y-1/2">/</kbd>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        {routes.isPending && <p className="px-3 py-2 text-muted">Loading…</p>}
        {routes.isError && <p className="px-3 py-2 text-bad">{routes.error.message}</p>}
        {routes.data?.length === 0 && <p className="px-3 py-2 text-muted">No routes yet. Add a spec to see them here.</p>}
        {routes.data && routes.data.length > 0 && groups.length === 0 && (
          <p className="px-3 py-2 text-muted">No routes match "{query}".</p>
        )}
        {groups.map(([tag, list]) => (
          <section key={tag} className="mb-1.5">
            <h3 className="truncate px-3 py-1 text-2xs font-medium uppercase tracking-wide text-muted">{tag}</h3>
            <ul>
              {list.map((route) => (
                <RouteRow key={route.key} route={route} active={route.key === selected} onSelect={() => onSelect(route.key)} />
              ))}
            </ul>
          </section>
        ))}
      </div>
      {orphans.length > 0 && (
        <section className="max-h-40 overflow-y-auto border-t border-line p-2" aria-label="Rules needing review">
          <h3 className="mb-1 flex items-center gap-1 text-xs font-medium text-warn">
            <AlertTriangle size={12} /> {plural(orphans.length, 'rule')} {orphans.length === 1 ? 'needs' : 'need'} review
          </h3>
          <p className="mb-1 text-2xs text-muted">Routes gone from the spec take their rules out of action.</p>
          <ul>
            {orphans.map((rule) => (
              <li key={rule.id}>
                <button
                  className="w-full truncate rounded px-1 py-0.5 text-left text-xs hover:bg-raised"
                  title={rule.route}
                  onClick={() => setDraft(draftFromRule(rule))}
                >
                  {rule.name} <span className="font-mono text-muted">{rule.route}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
