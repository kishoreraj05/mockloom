import { Plus } from 'lucide-react';
import type { RouteDetail, RuleOut } from '@/api/client';
import { useRules, useSaveRule } from '@/api/hooks';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { describeWhen, draftFromRule, draftToRule, emptyDraft } from '@/lib/rules';
import { statusTone } from '@/lib/utils';
import { useUi } from '@/store/ui';
import { RuleBuilder } from './RuleBuilder';

function RuleCard({ rule, slug }: { rule: RuleOut; slug: string }) {
  const save = useSaveRule(slug);
  const setDraft = useUi((state) => state.setDraft);
  const toast = useUi((state) => state.toast);
  const then = rule.then as { status?: number; body?: unknown; delay_ms?: number };
  const status = then.status ?? 200;
  return (
    <li className="flex items-center gap-2 border-t border-line px-3 py-2 first:border-t-0">
      <Switch
        label={`Enable ${rule.name}`}
        checked={rule.enabled}
        disabled={save.isPending}
        onCheckedChange={(enabled) =>
          save.mutate(
            { id: rule.id, rule: { ...draftToRule(draftFromRule(rule)), enabled } },
            { onError: (error) => toast(error.message, 'bad') },
          )
        }
      />
      <button className="min-w-0 flex-1 text-left" onClick={() => setDraft(draftFromRule(rule))}>
        <div className="flex items-baseline gap-2">
          <span className="truncate font-medium">{rule.name}</span>
          <span className={`font-mono text-xs ${statusTone(status)}`}>{status}</span>
          {Boolean(then.delay_ms) && <span className="text-2xs text-muted">+{then.delay_ms}ms</span>}
        </div>
        <div className="truncate text-xs text-muted">{describeWhen(rule.when)}</div>
      </button>
      <span className="font-mono text-2xs text-muted" title="Priority: lower numbers run first">
        #{rule.priority}
      </span>
    </li>
  );
}

export function RulesPanel({ slug, route }: { slug: string; route: RouteDetail }) {
  const rules = useRules(slug);
  const draft = useUi((state) => state.draft);
  const draftVersion = useUi((state) => state.draftVersion);
  const setDraft = useUi((state) => state.setDraft);

  if (draft) return <RuleBuilder key={draftVersion} slug={slug} route={route} />;

  const mine = rules.data?.filter((rule) => rule.route === route.key) ?? [];
  return (
    <div className="p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-xs text-muted">The first matching rule decides the response. Lower priority numbers run first.</p>
        <Button size="sm" variant="primary" className="shrink-0" onClick={() => setDraft(emptyDraft(route.key))}>
          <Plus size={13} /> New rule <kbd className="border-accent-ink/40 text-accent-ink">n</kbd>
        </Button>
      </div>
      {rules.isError && <p className="text-bad">{rules.error.message}</p>}
      {rules.data && mine.length === 0 && (
        <div className="rounded-lg border border-dashed border-line p-6 text-center text-muted">
          No rules yet, so this route returns data generated from the spec.
          <br />
          Add one to test an empty list, an error or a paywall.
        </div>
      )}
      {mine.length > 0 && (
        <ul className="rounded-lg border border-line bg-surface" aria-label="Rules for this route">
          {mine.map((rule) => (
            <RuleCard key={rule.id} rule={rule} slug={slug} />
          ))}
        </ul>
      )}
    </div>
  );
}
