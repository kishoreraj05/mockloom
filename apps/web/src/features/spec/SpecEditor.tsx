import { useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CircleX, FileUp, GitCompare } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, type SpecIssue, type SpecSaved } from '@/api/client';
import { useSaveSpec, useSpec, useSpecVersions, validateSpec } from '@/api/hooks';
import { CodeDiff, CodeEditor } from '@/components/LazyCode';
import { Button } from '@/components/ui/button';
import { cn, plural } from '@/lib/utils';

export function SpecEditor({ slug }: { slug: string }) {
  const spec = useSpec(slug);
  const versions = useSpecVersions(slug);
  const save = useSaveSpec(slug);
  const queryClient = useQueryClient();
  const [text, setText] = useState<string | null>(null);
  const [issues, setIssues] = useState<SpecIssue[]>([]);
  const [routeCount, setRouteCount] = useState<number | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [saved, setSaved] = useState<SpecSaved | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const active = spec.data?.text ?? '';
  const current = text ?? active;
  const dirty = current !== active;
  const language = current.trimStart().startsWith('{') ? 'json' : 'yaml';

  useEffect(() => {
    if (!current.trim()) {
      setIssues([]);
      setRouteCount(null);
      return;
    }
    let stale = false;
    const timer = window.setTimeout(async () => {
      try {
        const result = await validateSpec(current);
        if (stale) return;
        setIssues(result.issues);
        setRouteCount(result.ok ? result.route_count : null);
        setFailure(null);
      } catch (cause) {
        if (!stale) setFailure(cause instanceof Error ? cause.message : 'Could not check this spec.');
      }
    }, 500);
    return () => {
      stale = true;
      window.clearTimeout(timer);
    };
  }, [current]);

  const errors = issues.filter((issue) => issue.severity === 'error');
  const markers = useMemo(
    () =>
      issues
        .filter((issue) => issue.line)
        .map((issue) => ({ line: issue.line!, message: issue.message, severity: issue.severity })),
    [issues],
  );

  async function commit() {
    setFailure(null);
    try {
      const result = await save.mutateAsync(current);
      setSaved(result);
      setReviewing(false);
      setText(null);
      await queryClient.invalidateQueries({ queryKey: ['workspaces', slug] });
    } catch (cause) {
      if (cause instanceof ApiError && cause.issues.length) setIssues(cause.issues);
      setFailure(cause instanceof Error ? cause.message : 'Could not save this spec.');
      setReviewing(false);
    }
  }

  if (spec.isPending) return <div className="p-4 text-muted">Loading…</div>;
  if (spec.isError) return <div className="p-4 text-bad">{spec.error.message}</div>;

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface px-3 py-1.5">
        <h2 className="font-medium">Spec</h2>
        <span className="text-xs text-muted">
          {spec.data ? `Version ${spec.data.version} is live` : 'No spec yet'}
          {versions.data && versions.data.length > 1 && `, ${versions.data.length} versions kept`}
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          <Button size="sm" variant="ghost" onClick={() => fileInput.current?.click()}>
            <FileUp size={13} /> Upload
          </Button>
          <input
            ref={fileInput}
            type="file"
            aria-label="Spec file"
            accept=".yaml,.yml,.json"
            className="hidden"
            onChange={async (event) => {
              const file = event.target.files?.[0];
              if (file) setText(await file.text());
              event.target.value = '';
            }}
          />
          {dirty && !reviewing && (
            <Button size="sm" variant="ghost" onClick={() => setText(null)}>
              Discard
            </Button>
          )}
          {reviewing ? (
            <>
              <Button size="sm" onClick={() => setReviewing(false)}>
                Back to editing
              </Button>
              <Button size="sm" variant="primary" disabled={save.isPending} onClick={() => void commit()}>
                {save.isPending ? 'Saving…' : `Save as version ${(versions.data?.[0]?.version ?? 0) + 1}`}
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              variant="primary"
              disabled={!dirty || errors.length > 0 || !current.trim()}
              onClick={() => {
                setSaved(null);
                if (spec.data) setReviewing(true);
                else void commit(); // Nothing to compare the first version with.
              }}
            >
              <GitCompare size={13} /> {spec.data ? 'Review changes' : 'Save spec'}
            </Button>
          )}
        </div>
      </div>

      {saved && (
        <div className="border-b border-line bg-raised px-3 py-1.5 text-xs" role="status">
          <span className="text-ok">Version {saved.version} is live with {plural(saved.route_count, 'route')}.</span>
          {saved.orphaned_rules.length > 0 && (
            <span className="text-warn"> These rules lost their route and need review: {saved.orphaned_rules.join(', ')}.</span>
          )}
          {saved.restored_rules.length > 0 && <span> Back in action: {saved.restored_rules.join(', ')}.</span>}
        </div>
      )}

      <div className="min-h-0 flex-1">
        {reviewing ? (
          <CodeDiff original={active} modified={current} language={language} />
        ) : (
          <CodeEditor
            language={language}
            path={`spec-${slug}.${language}`}
            value={current}
            markers={markers}
            ariaLabel="OpenAPI spec"
            onChange={setText}
          />
        )}
      </div>

      <div className="max-h-40 overflow-y-auto border-t border-line bg-surface" aria-label="Spec problems">
        <p className="px-3 py-1 text-xs text-muted" role="status">
          {failure && <span className="text-bad">{failure} </span>}
          {errors.length > 0
            ? `${plural(errors.length, 'error')} ${errors.length === 1 ? 'stops' : 'stop'} this spec from loading.`
            : routeCount !== null
              ? `Valid: ${plural(routeCount, 'route')}${issues.length ? `, ${plural(issues.length, 'warning')}. Warnings don't stop it from serving.` : '.'}`
              : current.trim()
                ? 'Checking…'
                : 'Paste or upload an OpenAPI 3.0 or 3.1 spec.'}
        </p>
        {issues.length > 0 && (
          <ul>
            {issues.map((issue, index) => (
              <li key={index} className="flex items-start gap-1.5 border-t border-line px-3 py-1 text-xs">
                {issue.severity === 'error' ? (
                  <CircleX size={12} className="mt-0.5 shrink-0 text-bad" />
                ) : (
                  <AlertTriangle size={12} className="mt-0.5 shrink-0 text-warn" />
                )}
                <span className={cn('min-w-0 break-words')}>
                  {issue.line && <span className="font-mono text-muted">Line {issue.line}: </span>}
                  {issue.message}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
