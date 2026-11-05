import { Plus, Send, X } from 'lucide-react';
import { useState } from 'react';
import type { RouteDetail } from '@/api/client';
import { CodeEditor } from '@/components/LazyCode';
import { Button } from '@/components/ui/button';
import { Input, Label } from '@/components/ui/fields';
import { parameterSample } from '@/lib/rules';
import { prettyJson, statusTone } from '@/lib/utils';
import { type MockResponse, sendMockRequest } from './send';

interface Row {
  name: string;
  value: string;
}

function Rows({
  title,
  rows,
  onChange,
  addLabel,
}: {
  title: string;
  rows: Row[];
  onChange: (rows: Row[]) => void;
  addLabel: string;
}) {
  return (
    <div>
      <Label>{title}</Label>
      <div className="space-y-1.5">
        {rows.map((row, index) => (
          <div key={index} className="flex gap-1.5" role="group" aria-label={`${title} ${index + 1}`}>
            <Input
              aria-label={`${title} name`}
              placeholder="name"
              className="font-mono text-xs"
              value={row.name}
              onChange={(event) => onChange(rows.map((r, i) => (i === index ? { ...r, name: event.target.value } : r)))}
            />
            <Input
              aria-label={`${title} value`}
              placeholder="value"
              className="font-mono text-xs"
              value={row.value}
              onChange={(event) => onChange(rows.map((r, i) => (i === index ? { ...r, value: event.target.value } : r)))}
            />
            <Button
              size="icon"
              variant="ghost"
              aria-label={`Remove ${row.name || `${title} ${index + 1}`}`}
              onClick={() => onChange(rows.filter((_, i) => i !== index))}
            >
              <X size={13} />
            </Button>
          </div>
        ))}
      </div>
      <Button size="sm" variant="ghost" className="mt-1" onClick={() => onChange([...rows, { name: '', value: '' }])}>
        <Plus size={13} /> {addLabel}
      </Button>
    </div>
  );
}

export function TryIt({ slug, route }: { slug: string; route: RouteDetail }) {
  const pathParams = route.parameters.filter((p) => p.location === 'path');
  const [pathValues, setPathValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(pathParams.map((p) => [p.name, parameterSample(p)])),
  );
  const [query, setQuery] = useState<Row[]>(() =>
    route.parameters
      .filter((p) => p.location === 'query' && p.required)
      .map((p) => ({ name: p.name, value: parameterSample(p) })),
  );
  const [headers, setHeaders] = useState<Row[]>(() =>
    route.parameters
      .filter((p) => p.location === 'header' && p.required)
      .map((p) => ({ name: p.name, value: parameterSample(p) })),
  );
  const canHaveBody = !['GET', 'HEAD'].includes(route.method);
  const [body, setBody] = useState(() =>
    route.sample_body !== null && route.sample_body !== undefined ? JSON.stringify(route.sample_body, null, 2) : '',
  );
  const [response, setResponse] = useState<MockResponse | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    setSending(true);
    setFailure(null);
    setResponse(null);
    try {
      const path = route.path.replace(/\{([^}]+)\}/g, (_, name: string) => encodeURIComponent(pathValues[name] ?? ''));
      const toRecord = (rows: Row[]) => Object.fromEntries(rows.filter((r) => r.name.trim()).map((r) => [r.name.trim(), r.value]));
      setResponse(
        await sendMockRequest(slug, {
          method: route.method,
          path,
          query: toRecord(query),
          headers: toRecord(headers),
          body: canHaveBody && body.trim() ? body : undefined,
        }),
      );
    } catch (cause) {
      setFailure(cause instanceof Error ? cause.message : 'The request failed.');
    } finally {
      setSending(false);
    }
  }

  return (
    <form onSubmit={send} className="space-y-3 p-3" aria-label="Send a test request">
      {pathParams.length > 0 && (
        <div className="grid grid-cols-2 gap-2">
          {pathParams.map((parameter) => (
            <div key={parameter.name}>
              <Label htmlFor={`path-${parameter.name}`}>Path: {parameter.name}</Label>
              <Input
                id={`path-${parameter.name}`}
                className="font-mono text-xs"
                value={pathValues[parameter.name] ?? ''}
                onChange={(event) => setPathValues({ ...pathValues, [parameter.name]: event.target.value })}
              />
            </div>
          ))}
        </div>
      )}
      <Rows title="Query" rows={query} onChange={setQuery} addLabel="Add query parameter" />
      <Rows title="Header" rows={headers} onChange={setHeaders} addLabel="Add header" />
      {canHaveBody && (
        <div>
          <Label>Body</Label>
          <div className="h-36 overflow-hidden rounded border border-line">
            <CodeEditor language="json" path={`try-${route.key}.json`} value={body} onChange={setBody} ariaLabel="Request body" />
          </div>
        </div>
      )}
      <Button type="submit" variant="primary" disabled={sending}>
        <Send size={13} /> {sending ? 'Sending…' : 'Send request'}
      </Button>

      {failure && <p className="rounded border border-bad p-2 text-bad" role="alert">{failure}</p>}
      {response && (
        <section aria-label="Response" className="rounded border border-line bg-surface">
          <div className="flex flex-wrap items-baseline gap-x-3 border-b border-line px-2.5 py-1.5 text-xs">
            <span data-testid="try-status" className={`font-mono text-sm font-semibold ${statusTone(response.status)}`}>
              {response.status}
            </span>
            <span className="text-muted">{response.ms} ms</span>
            {response.rule ? (
              <span>
                Rule: <span className="font-medium">{response.rule}</span>
              </span>
            ) : (
              <span className="text-muted">From {response.source ?? 'mock'}</span>
            )}
          </div>
          <pre data-testid="try-body" className="max-h-80 overflow-auto whitespace-pre-wrap break-all p-2.5 font-mono text-xs">
            {prettyJson(response.body) || <span className="text-muted">Empty body</span>}
          </pre>
        </section>
      )}
    </form>
  );
}
