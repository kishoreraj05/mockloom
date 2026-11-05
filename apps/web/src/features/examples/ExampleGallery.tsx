import { ChevronRight } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { WorkspaceOut } from '@/api/client';
import { useCreateWorkspace } from '@/api/hooks';
import { CopyButton } from '@/components/CopyButton';
import { MethodBadge } from '@/components/MethodBadge';
import { Button } from '@/components/ui/button';
import { curlCommand, type Example, EXAMPLES, exampleRules, exampleSpec, type Scenario } from '@/lib/examples';
import { mockBaseUrl, plural, statusTone } from '@/lib/utils';
import { useUi } from '@/store/ui';

function ScenarioRow({ example, scenario }: { example: Example; scenario: Scenario }) {
  const command = curlCommand(mockBaseUrl(`/mock/${example.id}`), scenario);
  const query = new URLSearchParams(scenario.query ?? {}).toString();
  return (
    <li className="flex items-center gap-2 border-t border-line py-1.5 first:border-t-0">
      <div className="min-w-0 flex-1">
        <div className="text-xs">{scenario.label}</div>
        <div className="flex items-baseline">
          <MethodBadge method={scenario.method} />
          <code className="min-w-0 truncate font-mono text-2xs text-muted" title={command}>
            {scenario.path}
            {query && `?${query}`}
          </code>
        </div>
      </div>
      <span className={`font-mono text-xs font-medium ${statusTone(scenario.expect_status)}`}>{scenario.expect_status}</span>
      <CopyButton text={command} label={`Copy curl command: ${scenario.label}`} />
    </li>
  );
}

function ExampleRow({
  example,
  existing,
  onStartFrom,
}: {
  example: Example;
  existing: boolean;
  onStartFrom: (text: string) => void;
}) {
  const create = useCreateWorkspace();
  const navigate = useNavigate();
  const toast = useUi((state) => state.toast);
  const [open, setOpen] = useState(false);
  const rules = exampleRules(example.id);

  async function openExample() {
    try {
      await create.mutateAsync({
        name: example.name,
        slug: example.id,
        spec_text: exampleSpec(example.id),
        rules,
      });
      navigate(`/w/${example.id}`);
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : 'Could not create this example.', 'bad');
    }
  }

  return (
    <li className="border-t border-line px-3 py-2.5 first:border-t-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-0 flex-1 basis-64">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <h3 className="font-medium">{example.name}</h3>
            <span className="rounded bg-accent-soft px-1.5 text-2xs">{example.level}</span>
          </div>
          <p className="mt-0.5 text-xs text-muted">{example.description}</p>
          <p className="mt-0.5 text-2xs text-muted">
            OpenAPI {example.openapi} · {plural(example.routes, 'route')} · {plural(rules.length, 'rule')} · {example.shows.join(', ')}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <Button size="sm" variant="ghost" onClick={() => onStartFrom(exampleSpec(example.id))} aria-label={`Start from the ${example.name} spec`}>
            Start from this spec
          </Button>
          {existing ? (
            <Link
              to={`/w/${example.id}`}
              className="inline-flex h-7 items-center rounded border border-line bg-surface px-2 text-xs font-medium hover:bg-raised"
              aria-label={`Open your ${example.name} workspace`}
            >
              Open workspace
            </Link>
          ) : (
            <Button size="sm" disabled={create.isPending} onClick={() => void openExample()} aria-label={`Open the ${example.name} example`}>
              {create.isPending ? 'Creating…' : 'Open example'}
            </Button>
          )}
        </div>
      </div>
      <button
        type="button"
        aria-expanded={open}
        className="mt-1 flex items-center gap-0.5 text-xs text-muted hover:text-ink"
        onClick={() => setOpen(!open)}
      >
        <ChevronRight size={12} className={open ? 'rotate-90' : ''} />
        What to try ({example.try.length})
      </button>
      {open && (
        <div className="mt-1 pl-3.5">
          {!existing && <p className="mb-1 text-2xs text-muted">These commands work once the example is open.</p>}
          <ul aria-label={`Requests to try on ${example.name}`}>
            {example.try.map((scenario) => (
              <ScenarioRow key={scenario.label} example={example} scenario={scenario} />
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

export function ExampleGallery({
  workspaces,
  onStartFrom,
}: {
  workspaces: WorkspaceOut[] | undefined;
  onStartFrom: (text: string) => void;
}) {
  const slugs = new Set(workspaces?.map((workspace) => workspace.slug));
  return (
    <section className="mt-6" aria-label="Examples">
      <h2 className="text-sm font-semibold">Examples</h2>
      <p className="mb-2 text-xs text-muted">
        Open one to test it now, with its rules included, or start from its spec and change it to fit your API.
      </p>
      <ul className="rounded-lg border border-line bg-surface">
        {EXAMPLES.map((example) => (
          <ExampleRow key={example.id} example={example} existing={slugs.has(example.id)} onStartFrom={onStartFrom} />
        ))}
      </ul>
    </section>
  );
}
