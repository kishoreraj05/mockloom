import { useState } from 'react';
import type { RouteDetail } from '@/api/client';
import { useResponseSample, useRules } from '@/api/hooks';
import { CopyButton } from '@/components/CopyButton';
import { Select } from '@/components/ui/fields';
import { buildSampleRequest, describeWhen, draftFromRule } from '@/lib/rules';
import { absoluteUrl, SNIPPET_LANGUAGES, snippet, type SnippetLanguage, type SnippetRequest } from '@/lib/snippets';
import { mockBaseUrl, statusTone } from '@/lib/utils';

function CodeBlock({ code, label, testId }: { code: string; label: string; testId?: string }) {
  return (
    <div className="relative rounded border border-line bg-raised">
      <pre data-testid={testId} className="max-h-72 overflow-auto whitespace-pre-wrap break-all p-2.5 pr-9 font-mono text-xs">
        {code}
      </pre>
      <div className="absolute right-1 top-1">
        <CopyButton text={code} label={label} />
      </div>
    </div>
  );
}

function LanguagePicker({ value, onChange }: { value: SnippetLanguage; onChange: (value: SnippetLanguage) => void }) {
  return (
    <div role="radiogroup" aria-label="Code language" className="inline-flex rounded border border-line">
      {SNIPPET_LANGUAGES.map((language) => (
        <button
          key={language.value}
          type="button"
          role="radio"
          aria-checked={value === language.value}
          className={`h-6 px-2 text-xs first:rounded-l last:rounded-r ${
            value === language.value ? 'bg-accent-soft font-medium text-ink' : 'text-muted hover:text-ink'
          }`}
          onClick={() => onChange(language.value)}
        >
          {language.label}
        </button>
      ))}
    </div>
  );
}

function Heading({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-1 text-2xs font-medium uppercase tracking-wide text-muted">{children}</h3>;
}

export function UseInApp({ slug, route }: { slug: string; route: RouteDetail }) {
  const baseUrl = mockBaseUrl(`/mock/${slug}`);
  const [language, setLanguage] = useState<SnippetLanguage>('curl');
  const statuses = route.responses.map((response) => response.status);
  const [picked, setPicked] = useState<string | null>(null);
  const status = picked && statuses.includes(picked) ? picked : (statuses[0] ?? '200');
  const sample = useResponseSample(slug, route.key, status);
  const rules = useRules(slug);

  const request: SnippetRequest = buildSampleRequest(route, { mode: 'all', conditions: [] });
  const mine = rules.data?.filter((rule) => rule.route === route.key && rule.enabled && !rule.orphaned) ?? [];
  const body = sample.data?.body;

  return (
    <div className="space-y-4 p-3">
      <section>
        <Heading>Base URL for your app</Heading>
        <CodeBlock code={baseUrl} label="Copy base URL" />
        <p className="mt-1 text-2xs text-muted">
          Point your app's API base URL here. Browser apps can call it from any origin. It can be reached wherever this
          address can; a <code className="font-mono">localhost</code> address only works on this computer.
        </p>
      </section>

      <section>
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
          <Heading>Example request</Heading>
          <LanguagePicker value={language} onChange={setLanguage} />
        </div>
        <CodeBlock code={snippet(language, baseUrl, request)} label="Copy example request" testId="snippet" />
        <p className="mt-1 text-2xs text-muted">
          Uses dummy values that pass this route's validation. Link: <span className="break-all font-mono">{absoluteUrl(baseUrl, request)}</span>
        </p>
      </section>

      <section>
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-2xs font-medium uppercase tracking-wide text-muted">Example response</h3>
          {statuses.length > 1 && (
            <Select
              aria-label="Response status"
              className="h-6 w-auto font-mono text-xs"
              value={status}
              onChange={(event) => setPicked(event.target.value)}
            >
              {statuses.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </Select>
          )}
        </div>
        {sample.isError && <p className="text-bad">{sample.error.message}</p>}
        {sample.data && (
          <>
            {body === null || body === undefined ? (
              <p className="rounded border border-line bg-raised p-2.5 text-xs text-muted">This response has no body.</p>
            ) : (
              <CodeBlock
                code={typeof body === 'string' ? body : JSON.stringify(body, null, 2)}
                label="Copy example response"
              />
            )}
            <p className="mt-1 text-2xs text-muted">
              Shows the shape from the spec. Generated values differ by URL, but stay the same for the same URL and seed.
            </p>
          </>
        )}
      </section>

      {mine.length > 0 && (
        <section>
          <Heading>Example request for each rule</Heading>
          <p className="mb-2 text-2xs text-muted">
            Each one meets its rule's conditions. If it also meets a rule with a lower priority number, that rule answers
            instead; the <code className="font-mono">x-mockloom-rule</code> response header tells you which one did.
          </p>
          <div className="space-y-3">
            {mine.map((rule) => {
              const triggered = buildSampleRequest(route, draftFromRule(rule));
              const expected = (rule.then as { status?: number }).status ?? 200;
              return (
                <div key={rule.id} role="group" aria-label={`To get: ${rule.name}`}>
                  <p className="mb-1 text-xs">
                    <span className="font-medium">{rule.name}</span>{' '}
                    <span className={`font-mono ${statusTone(expected)}`}>{expected}</span>{' '}
                    <span className="text-muted">when {describeWhen(rule.when)}</span>
                  </p>
                  <CodeBlock
                    code={snippet(language, baseUrl, triggered)}
                    label={`Copy request for ${rule.name}`}
                    testId="snippet"
                  />
                  {triggered.warnings.map((warning) => (
                    <p key={warning} className="mt-1 text-2xs text-warn">
                      {warning}
                    </p>
                  ))}
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
