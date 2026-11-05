import { Play, Plus, Trash2, X } from 'lucide-react';
import { useState } from 'react';
import { ApiError, type RouteDetail } from '@/api/client';
import { useDeleteRule, useResponseSample, useSaveRule } from '@/api/hooks';
import { CodeEditor } from '@/components/LazyCode';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/dialog';
import { Input, Label, Select, Textarea } from '@/components/ui/fields';
import { sendMockRequest } from '@/features/tryit/send';
import {
  buildSampleRequest,
  type ConditionRow,
  DraftError,
  draftToRule,
  OPERATORS,
  type Operator,
  type Source,
  SOURCES,
} from '@/lib/rules';
import { statusTone } from '@/lib/utils';
import { useUi } from '@/store/ui';

const NUMBER_STATUSES = [200, 201, 204, 400, 401, 402, 403, 404, 409, 422, 429, 500, 502, 503];

function ConditionEditor({
  row,
  index,
  route,
  onChange,
  onRemove,
}: {
  row: ConditionRow;
  index: number;
  route: RouteDetail;
  onChange: (patch: Partial<ConditionRow>) => void;
  onRemove: () => void;
}) {
  const hints = route.parameters
    .filter((parameter) => parameter.location === row.source)
    .map((parameter) => parameter.name);
  const listId = `condition-fields-${index}`;
  const fieldPlaceholder = row.source === 'body' ? '$.items[0].sku' : row.source === 'header' ? 'x-user-tier' : 'name';
  return (
    <div className="flex flex-wrap items-start gap-1.5" role="group" aria-label={`Condition ${index + 1}`}>
      <Select
        aria-label="Source"
        className="w-[116px] text-xs"
        value={row.source}
        onChange={(event) => onChange({ source: event.target.value as Source })}
      >
        {SOURCES.map((source) => (
          <option key={source.value} value={source.value}>
            {source.label}
          </option>
        ))}
      </Select>
      <Input
        aria-label="Field"
        list={listId}
        placeholder={fieldPlaceholder}
        className="min-w-24 flex-1 font-mono text-xs"
        value={row.field}
        onChange={(event) => onChange({ field: event.target.value })}
      />
      <datalist id={listId}>
        {hints.map((hint) => (
          <option key={hint} value={hint} />
        ))}
      </datalist>
      <Select
        aria-label="Operator"
        className="w-[124px] text-xs"
        value={row.op}
        onChange={(event) => onChange({ op: event.target.value as Operator })}
      >
        {OPERATORS.map((operator) => (
          <option key={operator.value} value={operator.value}>
            {operator.label}
          </option>
        ))}
      </Select>
      {row.op === 'matches_schema' ? (
        <Textarea
          aria-label="JSON Schema"
          rows={3}
          placeholder='{"type": "object"}'
          className="min-w-full font-mono text-xs"
          value={row.value}
          onChange={(event) => onChange({ value: event.target.value })}
        />
      ) : (
        row.op !== 'exists' && row.op !== 'missing' && (
          <Input
            aria-label="Value"
            placeholder={OPERATORS.find((o) => o.value === row.op)?.hint ?? 'value'}
            className="min-w-24 flex-1 font-mono text-xs"
            value={row.value}
            onChange={(event) => onChange({ value: event.target.value })}
          />
        )
      )}
      <Button size="icon" variant="ghost" aria-label={`Remove condition ${index + 1}`} onClick={onRemove}>
        <X size={13} />
      </Button>
    </div>
  );
}

interface TestResult {
  status: number;
  matched: boolean;
  matchedName: string | null;
  warnings: string[];
  failed?: string;
}

export function RuleBuilder({ slug, route }: { slug: string; route: RouteDetail }) {
  const draft = useUi((state) => state.draft)!;
  const draftVersion = useUi((state) => state.draftVersion);
  const patch = useUi((state) => state.patchDraft);
  const setDraft = useUi((state) => state.setDraft);
  const toast = useUi((state) => state.toast);
  const save = useSaveRule(slug);
  const remove = useDeleteRule(slug);
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const sample = useResponseSample(slug, route.key, String(draft.status));
  const orphanedElsewhere = draft.route !== route.key;

  const statuses = [
    ...new Set([...route.responses.map((r) => Number(r.status)).filter(Number.isInteger), ...NUMBER_STATUSES, draft.status]),
  ].sort((a, b) => a - b);
  const declared = new Set(route.responses.map((r) => r.status));

  function updateCondition(index: number, change: Partial<ConditionRow>) {
    patch({ conditions: draft.conditions.map((row, i) => (i === index ? { ...row, ...change } : row)) });
  }

  async function persist(): Promise<boolean> {
    setError(null);
    try {
      const saved = await save.mutateAsync({ id: draft.id, rule: draftToRule(draft) });
      patch({ id: saved.id });
      return true;
    } catch (cause) {
      setError(cause instanceof DraftError || cause instanceof ApiError ? cause.message : 'Could not save this rule.');
      return false;
    }
  }

  async function runTest() {
    setTest(null);
    setTesting(true);
    try {
      if (!(await persist())) return;
      const request = buildSampleRequest(route, draft);
      const result = await sendMockRequest(slug, request);
      setTest({
        status: result.status,
        matchedName: result.rule,
        matched: result.rule === draft.name.trim(),
        warnings: request.warnings,
      });
    } catch (cause) {
      setTest({
        status: 0,
        matched: false,
        matchedName: null,
        warnings: [],
        failed: cause instanceof Error ? cause.message : 'The request failed.',
      });
    } finally {
      setTesting(false);
    }
  }

  return (
    <form
      className="space-y-4 p-3"
      aria-label={draft.id ? 'Edit rule' : 'New rule'}
      onSubmit={async (event) => {
        event.preventDefault();
        if (await persist()) {
          toast(`Saved "${draft.name.trim()}". It applies to the next request.`);
          setDraft(null);
        }
      }}
    >
      {orphanedElsewhere && (
        <p className="rounded border border-line bg-raised p-2 text-xs text-warn">
          This rule targets <code className="font-mono">{draft.route}</code>, which is gone from the spec. Saving moves it to{' '}
          <code className="font-mono">{route.key}</code>, the route selected on the left.
        </p>
      )}
      <div className="grid grid-cols-[minmax(0,1fr)_72px] gap-2">
        <div>
          <Label htmlFor="rule-name">Rule name</Label>
          <Input
            id="rule-name"
            autoFocus={!draft.id}
            placeholder="Empty cart"
            value={draft.name}
            onChange={(event) => patch({ name: event.target.value })}
          />
        </div>
        <div>
          <Label htmlFor="rule-priority">Priority</Label>
          <Input
            id="rule-priority"
            type="number"
            title="Lower numbers run first"
            value={draft.priority}
            onChange={(event) => patch({ priority: Number(event.target.value) })}
          />
        </div>
      </div>

      <fieldset>
        <div className="mb-1.5 flex items-center gap-2">
          <legend className="text-2xs font-medium uppercase tracking-wide text-muted">When</legend>
          {draft.conditions.length > 1 && (
            <Select
              aria-label="Combine conditions"
              className="h-6 w-auto text-xs"
              value={draft.mode}
              onChange={(event) => patch({ mode: event.target.value as 'all' | 'any' })}
            >
              <option value="all">all of these match</option>
              <option value="any">any of these match</option>
            </Select>
          )}
        </div>
        <div className="space-y-1.5">
          {draft.conditions.map((row, index) => (
            <ConditionEditor
              key={index}
              row={row}
              index={index}
              route={route}
              onChange={(change) => updateCondition(index, change)}
              onRemove={() => patch({ conditions: draft.conditions.filter((_, i) => i !== index) })}
            />
          ))}
          {draft.conditions.length === 0 && <p className="text-xs text-muted">No conditions, so this rule matches every request.</p>}
        </div>
        <Button
          size="sm"
          variant="ghost"
          className="mt-1"
          onClick={() => patch({ conditions: [...draft.conditions, { source: 'query', field: '', op: 'eq', value: '' }] })}
        >
          <Plus size={13} /> Add condition
        </Button>
      </fieldset>

      <fieldset>
        <legend className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-muted">Then respond with</legend>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <Label htmlFor="rule-status">Status</Label>
            <Select
              id="rule-status"
              className="w-40 font-mono text-xs"
              value={draft.status}
              onChange={(event) => patch({ status: Number(event.target.value) })}
            >
              {statuses.map((status) => (
                <option key={status} value={status}>
                  {status}{declared.has(String(status)) ? ' (in spec)' : ''}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="rule-delay">Delay (ms)</Label>
            <Input
              id="rule-delay"
              type="number"
              min={0}
              max={60000}
              className="w-24"
              value={draft.delayMs}
              onChange={(event) => patch({ delayMs: Number(event.target.value) })}
            />
          </div>
          <div role="radiogroup" aria-label="Response body" className="flex rounded border border-line">
            {(
              [
                ['generated', 'Generate from spec'],
                ['custom', 'Custom body'],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={draft.bodyMode === value}
                className={`h-8 px-2.5 text-xs first:rounded-l last:rounded-r ${
                  draft.bodyMode === value ? 'bg-accent-soft font-medium text-ink' : 'text-muted hover:text-ink'
                }`}
                onClick={() =>
                  patch({
                    bodyMode: value,
                    // Start custom bodies from the spec's shape instead of a blank editor.
                    bodyText:
                      value === 'custom' && !draft.bodyText && sample.data?.body !== undefined && sample.data.body !== null
                        ? JSON.stringify(sample.data.body, null, 2)
                        : draft.bodyText,
                  })
                }
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {draft.bodyMode === 'custom' && (
          <div className="mt-2">
            <div className="h-56 overflow-hidden rounded border border-line">
              <CodeEditor
                language="json"
                path={`rule-${draftVersion}.json`}
                value={draft.bodyText}
                schema={sample.data?.schema}
                ariaLabel="Response body"
                onChange={(bodyText) => patch({ bodyText })}
              />
            </div>
            <p className="mt-1 text-2xs text-muted">
              Templates work in any string: <code className="font-mono">{'{{request.path.id}}'}</code>,{' '}
              <code className="font-mono">{'{{request.query.q}}'}</code>, <code className="font-mono">{'{{request.body.name}}'}</code>,{' '}
              <code className="font-mono">{'{{faker.email}}'}</code>, <code className="font-mono">{'{{now}}'}</code>.
            </p>
          </div>
        )}

        <div className="mt-2 space-y-1.5">
          {draft.headers.map((header, index) => (
            <div key={index} className="flex gap-1.5" role="group" aria-label={`Response header ${index + 1}`}>
              <Input
                aria-label="Header name"
                placeholder="x-request-id"
                className="font-mono text-xs"
                value={header.name}
                onChange={(event) =>
                  patch({ headers: draft.headers.map((h, i) => (i === index ? { ...h, name: event.target.value } : h)) })
                }
              />
              <Input
                aria-label="Header value"
                placeholder="value"
                className="font-mono text-xs"
                value={header.value}
                onChange={(event) =>
                  patch({ headers: draft.headers.map((h, i) => (i === index ? { ...h, value: event.target.value } : h)) })
                }
              />
              <Button
                size="icon"
                variant="ghost"
                aria-label={`Remove header ${index + 1}`}
                onClick={() => patch({ headers: draft.headers.filter((_, i) => i !== index) })}
              >
                <X size={13} />
              </Button>
            </div>
          ))}
          <Button size="sm" variant="ghost" onClick={() => patch({ headers: [...draft.headers, { name: '', value: '' }] })}>
            <Plus size={13} /> Add response header
          </Button>
        </div>
      </fieldset>

      {error && <p className="rounded border border-bad p-2 text-bad" role="alert">{error}</p>}

      {test && (
        <div className="rounded border border-line bg-raised p-2 text-xs" role="status">
          {test.failed ? (
            <p className="text-bad">{test.failed}</p>
          ) : (
            <p>
              <span className={`font-mono font-medium ${statusTone(test.status)}`}>{test.status}</span>{' '}
              {test.matched ? (
                <span className="text-ok">This rule matched the sample request.</span>
              ) : test.matchedName ? (
                <span className="text-warn">Rule "{test.matchedName}" matched first; lower its priority number to change that.</span>
              ) : (
                <span className="text-warn">This rule did not match the sample request.</span>
              )}
            </p>
          )}
          {test.warnings.map((warning) => (
            <p key={warning} className="mt-1 text-muted">{warning}</p>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Save rule'}
        </Button>
        <Button onClick={runTest} disabled={testing || save.isPending}>
          <Play size={13} /> {testing ? 'Testing…' : 'Test this rule'}
        </Button>
        <Button variant="ghost" onClick={() => setDraft(null)}>
          Close
        </Button>
        {draft.id && (
          <Button variant="danger" className="ml-auto" onClick={() => setConfirming(true)}>
            <Trash2 size={13} /> Delete
          </Button>
        )}
      </div>

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={`Delete "${draft.name}"?`}
        description="The route goes back to what it returned without this rule."
        confirmLabel="Delete rule"
        onConfirm={() =>
          remove.mutate(draft.id!, {
            onSuccess: () => setDraft(null),
            onError: (cause) => toast(cause.message, 'bad'),
          })
        }
      />
    </form>
  );
}
