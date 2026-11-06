import { FileUp, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError, type SpecValidation, type WorkspaceOut } from '@/api/client';
import { useCreateWorkspace, useDeleteWorkspace, useWorkspaces, validateSpec } from '@/api/hooks';
import { CopyButton } from '@/components/CopyButton';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/dialog';
import { Input, Label, Textarea } from '@/components/ui/fields';
import { ExampleGallery } from '@/features/examples/ExampleGallery';
import { mockBaseUrl, plural } from '@/lib/utils';
import { useUi } from '@/store/ui';

function NewWorkspace({ seed }: { seed: { text: string; version: number } | null }) {
  const [name, setName] = useState('');
  const [text, setText] = useState('');
  const form = useRef<HTMLFormElement>(null);
  const [check, setCheck] = useState<SpecValidation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const create = useCreateWorkspace();
  const navigate = useNavigate();

  // "Start from this spec" in the gallery. Clearing the name lets the new spec's title fill it in.
  useEffect(() => {
    if (!seed) return;
    setName('');
    setText(seed.text);
    form.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [seed]);

  useEffect(() => {
    setError(null);
    if (!text.trim()) {
      setCheck(null);
      return;
    }
    let stale = false;
    const timer = window.setTimeout(async () => {
      try {
        const result = await validateSpec(text);
        if (stale) return;
        setCheck(result);
        if (result.ok && result.title) setName((current) => current || result.title!);
      } catch (cause) {
        if (!stale) setError(cause instanceof ApiError ? cause.message : 'Could not check this spec.');
      }
    }, 300);
    return () => {
      stale = true;
      window.clearTimeout(timer);
    };
  }, [text]);

  async function readFile(file: File | undefined) {
    if (file) setText(await file.text());
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      const workspace = await create.mutateAsync({
        name: name.trim() || check?.title || 'Untitled workspace',
        spec_text: text.trim() ? text : null,
      });
      navigate(`/w/${workspace.slug}`);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Could not create the workspace.');
    }
  }

  const firstError = check?.issues.find((issue) => issue.severity === 'error');
  const warnings = check?.issues.filter((issue) => issue.severity === 'warning').length ?? 0;

  return (
    <form ref={form} onSubmit={submit} className="rounded-lg border border-line bg-surface p-4">
      <h2 className="text-sm font-semibold">Start from a spec</h2>
      <p className="mt-0.5 text-muted">OpenAPI 3.0 or 3.1, as YAML or JSON, up to 5 MB.</p>

      <div className="mt-3">
        <Label htmlFor="spec-text">Spec</Label>
        <div
          className={dragging ? 'rounded ring-2 ring-accent' : ''}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            void readFile(event.dataTransfer.files[0]);
          }}
        >
          <Textarea
            id="spec-text"
            value={text}
            onChange={(event) => setText(event.target.value)}
            rows={9}
            spellCheck={false}
            placeholder="Paste a spec, or drop a file here"
            className="resize-y font-mono text-xs"
          />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => fileInput.current?.click()}>
            <FileUp size={13} /> Upload file
          </Button>
          <input
            ref={fileInput}
            type="file"
            aria-label="Spec file"
            accept=".yaml,.yml,.json"
            className="hidden"
            onChange={(event) => void readFile(event.target.files?.[0])}
          />
          <span className="ml-auto text-xs" role="status" data-testid="spec-check">
            {firstError && <span className="text-bad">{firstError.line ? `Line ${firstError.line}: ` : ''}{firstError.message}</span>}
            {check?.ok && (
              <span className="text-ok">
                {check.title}, OpenAPI {check.openapi_version}, {plural(check.route_count, 'route')}
                {warnings > 0 && <span className="text-warn"> ({plural(warnings, 'warning')})</span>}
              </span>
            )}
          </span>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <div className="min-w-48 flex-1">
          <Label htmlFor="workspace-name">Workspace name</Label>
          <Input
            id="workspace-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Taken from the spec's title"
          />
        </div>
        <Button
          type="submit"
          variant="primary"
          disabled={create.isPending || Boolean(firstError) || (!text.trim() && !name.trim())}
        >
          {create.isPending ? 'Creating…' : 'Create mock server'}
        </Button>
      </div>
      {error && <p className="mt-2 text-bad" role="alert">{error}</p>}
    </form>
  );
}

function WorkspaceRow({ workspace, onDelete }: { workspace: WorkspaceOut; onDelete: () => void }) {
  const url = mockBaseUrl(workspace.mock_path);
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line px-3 py-2.5 first:border-t-0">
      <div className="min-w-0 flex-1 basis-56">
        <Link to={`/w/${workspace.slug}`} className="font-medium hover:text-accent hover:underline">
          {workspace.name}
        </Link>
        <div className="flex items-center gap-1 text-xs text-muted">
          <code className="truncate font-mono">{url}</code>
          <CopyButton text={url} label={`Copy mock URL for ${workspace.name}`} />
        </div>
      </div>
      <span className="text-xs text-muted">
        {plural(workspace.route_count, 'route')}, {plural(workspace.rule_count, 'rule')}
      </span>
      <Button size="icon" variant="ghost" aria-label={`Delete ${workspace.name}`} onClick={onDelete}>
        <Trash2 size={13} />
      </Button>
    </li>
  );
}

export function WorkspaceListPage() {
  const workspaces = useWorkspaces();
  const remove = useDeleteWorkspace();
  const toast = useUi((state) => state.toast);
  const [deleting, setDeleting] = useState<WorkspaceOut | null>(null);
  const [seed, setSeed] = useState<{ text: string; version: number } | null>(null);

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight">MockLoom</h1>
        <p className="mt-1 text-muted">Upload a spec, get a live mock server, and shape its responses with rules.</p>
      </header>

      <NewWorkspace seed={seed} />

      {workspaces.isError && <p className="mt-6 text-bad">{workspaces.error.message}</p>}
      {Boolean(workspaces.data?.length) && (
        <section className="mt-6" aria-label="Workspaces">
          <h2 className="mb-2 text-sm font-semibold">Workspaces</h2>
          <ul className="rounded-lg border border-line bg-surface">
            {workspaces.data!.map((workspace) => (
              <WorkspaceRow key={workspace.id} workspace={workspace} onDelete={() => setDeleting(workspace)} />
            ))}
          </ul>
        </section>
      )}

      <ExampleGallery
        workspaces={workspaces.data}
        onStartFrom={(text) => setSeed((current) => ({ text, version: (current?.version ?? 0) + 1 }))}
      />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete ${deleting?.name}?`}
        description="This removes its spec versions, rules and request log, and its mock URL stops working. This can't be undone."
        confirmLabel="Delete workspace"
        onConfirm={() => {
          if (deleting) {
            remove.mutate(deleting.slug, { onError: (error) => toast(error.message, 'bad') });
          }
        }}
      />
    </main>
  );
}
