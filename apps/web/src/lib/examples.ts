import catalog from '../../../../examples/catalog.json';
import type { RuleIn } from '@/api/client';

// The app ships with its examples, so the gallery works on any install with no extra setup.
const specFiles = import.meta.glob<string>('../../../../examples/specs/*.yaml', {
  query: '?raw',
  import: 'default',
  eager: true,
});
const ruleFiles = import.meta.glob<RuleIn>('../../../../examples/rules/*/*.json', {
  import: 'default',
  eager: true,
});

export interface Scenario {
  label: string;
  method: string;
  path: string;
  query?: Record<string, string>;
  headers?: Record<string, string>;
  body?: unknown;
  expect_status: number;
  expect_rule: string | null;
}

export interface Example {
  id: string;
  name: string;
  level: string;
  description: string;
  openapi: string;
  routes: number;
  shows: string[];
  try: Scenario[];
}

export const EXAMPLES = catalog as Example[];

export function exampleSpec(id: string): string {
  return specFiles[`../../../../examples/specs/${id}.yaml`];
}

export function exampleRules(id: string): RuleIn[] {
  const prefix = `../../../../examples/rules/${id}/`;
  return Object.keys(ruleFiles)
    .filter((path) => path.startsWith(prefix))
    .sort()
    .map((path) => ruleFiles[path]);
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

/** A command that can be pasted into a terminal as is. */
export function curlCommand(baseUrl: string, scenario: Scenario): string {
  const query = new URLSearchParams(scenario.query ?? {}).toString();
  const parts = ['curl', '-i'];
  if (scenario.method !== 'GET') parts.push('-X', scenario.method);
  parts.push(shellQuote(`${baseUrl}${scenario.path}${query ? `?${query}` : ''}`));
  for (const [name, value] of Object.entries(scenario.headers ?? {})) {
    parts.push('-H', shellQuote(`${name}: ${value}`));
  }
  if (scenario.body !== undefined) {
    parts.push('-H', shellQuote('content-type: application/json'), '-d', shellQuote(JSON.stringify(scenario.body)));
  }
  return parts.join(' ');
}
