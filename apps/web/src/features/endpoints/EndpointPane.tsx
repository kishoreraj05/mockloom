import * as Tabs from '@radix-ui/react-tabs';
import { useEffect } from 'react';
import { useRouteDetail } from '@/api/hooks';
import { MethodBadge } from '@/components/MethodBadge';
import { RouteChaos } from '@/features/chaos/ChaosBoard';
import { RulesPanel } from '@/features/rules/RulesPanel';
import { TryIt } from '@/features/tryit/TryIt';
import { type EndpointTab, useUi } from '@/store/ui';

const tabClass =
  'border-b-2 border-transparent px-3 py-1.5 text-xs text-muted hover:text-ink data-[state=active]:border-accent data-[state=active]:font-medium data-[state=active]:text-ink';

export function EndpointPane({ slug, routeKey }: { slug: string; routeKey: string }) {
  const detail = useRouteDetail(slug, routeKey);
  const tab = useUi((state) => state.tab);
  const setTab = useUi((state) => state.setTab);
  const draft = useUi((state) => state.draft);
  const setDraft = useUi((state) => state.setDraft);

  // Switching routes abandons a draft for the old route, unless it is an orphan under review.
  useEffect(() => {
    if (draft && draft.route !== routeKey && !draft.id) setDraft(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeKey]);

  if (detail.isPending) return <div className="p-4 text-muted">Loading…</div>;
  if (detail.isError) {
    return (
      <div className="p-4">
        <p className="font-medium">This route isn't in the active spec.</p>
        <p className="text-muted">{detail.error.message}</p>
      </div>
    );
  }
  const route = detail.data;

  return (
    <Tabs.Root value={tab} onValueChange={(value) => setTab(value as EndpointTab)} className="flex h-full flex-col">
      <div className="border-b border-line bg-surface px-3 pt-2.5">
        <div className="flex items-baseline gap-1">
          <MethodBadge method={route.method} className="text-xs" />
          <h2 className="min-w-0 break-all font-mono text-[13px] font-medium">{route.path}</h2>
        </div>
        {route.summary && <p className="mt-0.5 text-xs text-muted">{route.summary}</p>}
        <Tabs.List className="mt-1.5 flex" aria-label="Endpoint tools">
          <Tabs.Trigger value="rules" className={tabClass}>
            Rules{route.rule_count > 0 && ` (${route.rule_count})`}
          </Tabs.Trigger>
          <Tabs.Trigger value="try" className={tabClass}>
            Try it
          </Tabs.Trigger>
          <Tabs.Trigger value="chaos" className={tabClass}>
            Chaos
          </Tabs.Trigger>
        </Tabs.List>
      </div>
      <Tabs.Content value="rules" className="min-h-0 flex-1 overflow-y-auto">
        <RulesPanel slug={slug} route={route} />
      </Tabs.Content>
      <Tabs.Content value="try" className="min-h-0 flex-1 overflow-y-auto">
        <TryIt key={route.key} slug={slug} route={route} />
      </Tabs.Content>
      <Tabs.Content value="chaos" className="min-h-0 flex-1 overflow-y-auto">
        <RouteChaos slug={slug} routeKey={route.key} />
      </Tabs.Content>
    </Tabs.Root>
  );
}
