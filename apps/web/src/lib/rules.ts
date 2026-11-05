import type { LogEntry, RouteDetail, RuleIn, RuleOut } from '@/api/client';

export type Source = 'path' | 'query' | 'header' | 'cookie' | 'body';
/** `missing` exists only in the form. To the API it is `exists` with the value false. */
export type Operator = 'eq' | 'neq' | 'in' | 'contains' | 'regex' | 'gt' | 'lt' | 'exists' | 'missing' | 'matches_schema';

export const SOURCES: { value: Source; label: string }[] = [
  { value: 'query', label: 'Query' },
  { value: 'path', label: 'Path param' },
  { value: 'header', label: 'Header' },
  { value: 'cookie', label: 'Cookie' },
  { value: 'body', label: 'Body (JSONPath)' },
];

export const OPERATORS: { value: Operator; label: string; hint?: string }[] = [
  { value: 'eq', label: 'equals' },
  { value: 'neq', label: 'does not equal' },
  { value: 'in', label: 'is one of', hint: 'Comma-separated values' },
  { value: 'contains', label: 'contains' },
  { value: 'regex', label: 'matches regex' },
  { value: 'gt', label: 'greater than' },
  { value: 'lt', label: 'less than' },
  { value: 'exists', label: 'exists' },
  { value: 'missing', label: 'is missing' },
  { value: 'matches_schema', label: 'matches schema', hint: 'JSON Schema' },
];

export interface ConditionRow {
  source: Source;
  field: string;
  op: Operator;
  value: string;
}

export interface HeaderRow {
  name: string;
  value: string;
}

export interface RuleDraft {
  id?: string;
  name: string;
  route: string;
  priority: number;
  enabled: boolean;
  mode: 'all' | 'any';
  conditions: ConditionRow[];
  status: number;
  /** "generated" leaves the body out, so the server builds one from the spec's schema. */
  bodyMode: 'custom' | 'generated';
  bodyText: string;
  delayMs: number;
  headers: HeaderRow[];
}

export function emptyDraft(route: string): RuleDraft {
  return {
    name: '',
    route,
    priority: 100,
    enabled: true,
    mode: 'all',
    conditions: [{ source: 'query', field: '', op: 'eq', value: '' }],
    status: 200,
    bodyMode: 'generated',
    bodyText: '',
    delayMs: 0,
    headers: [],
  };
}

function valueToText(op: string, value: unknown): string {
  if (value === null || value === undefined) return '';
  if (op === 'in' && Array.isArray(value)) return value.map(String).join(', ');
  if (op === 'matches_schema') return JSON.stringify(value, null, 2);
  return typeof value === 'string' ? value : JSON.stringify(value);
}

export function draftFromRule(rule: RuleOut): RuleDraft {
  const when = rule.when as { all?: ConditionLike[]; any?: ConditionLike[] };
  const then = rule.then as {
    status?: number;
    body?: unknown;
    headers?: Record<string, string>;
    delay_ms?: number;
  };
  const conditions = when.any ?? when.all ?? [];
  const hasBody = 'body' in then;
  return {
    id: rule.id,
    name: rule.name,
    route: rule.route,
    priority: rule.priority,
    enabled: rule.enabled,
    mode: when.any ? 'any' : 'all',
    conditions: conditions.map((c) =>
      isMissing(c)
        ? { source: c.source, field: c.field, op: 'missing' as const, value: '' }
        : { source: c.source, field: c.field, op: c.op, value: valueToText(c.op, c.value) },
    ),
    status: then.status ?? 200,
    bodyMode: hasBody ? 'custom' : 'generated',
    bodyText: hasBody
      ? typeof then.body === 'string'
        ? then.body
        : JSON.stringify(then.body, null, 2)
      : '',
    delayMs: then.delay_ms ?? 0,
    headers: Object.entries(then.headers ?? {}).map(([name, value]) => ({ name, value })),
  };
}

interface ConditionLike {
  source: Source;
  field: string;
  op: Operator;
  value?: unknown;
}

function isMissing(condition: ConditionLike): boolean {
  return condition.op === 'exists' && condition.value === false;
}

function conditionValue(row: ConditionRow): unknown {
  switch (row.op) {
    case 'exists':
      return null;
    case 'missing':
      return false;
    case 'in':
      return row.value
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean);
    case 'gt':
    case 'lt':
      return Number(row.value);
    case 'matches_schema':
      return JSON.parse(row.value);
    default:
      return row.value;
  }
}

export class DraftError extends Error {}

/** Turn the form into the API's rule shape. Throws DraftError with a message fit to show. */
export function draftToRule(draft: RuleDraft): RuleIn {
  if (!draft.name.trim()) throw new DraftError('Give this rule a name.');
  const conditions = draft.conditions.filter((row) => row.field.trim());
  for (const row of conditions) {
    if ((row.op === 'gt' || row.op === 'lt') && !Number.isFinite(Number(row.value))) {
      throw new DraftError(`"${row.field}" needs a number to compare with.`);
    }
    if (row.op === 'matches_schema') {
      try {
        JSON.parse(row.value);
      } catch {
        throw new DraftError(`The schema for "${row.field}" is not valid JSON.`);
      }
    }
  }
  const headers = Object.fromEntries(
    draft.headers.filter((h) => h.name.trim()).map((h) => [h.name.trim(), h.value]),
  );
  const then: Record<string, unknown> = { status: draft.status, delay_ms: draft.delayMs, headers };
  if (draft.bodyMode === 'custom') {
    const contentType = Object.entries(headers).find(([name]) => name.toLowerCase() === 'content-type')?.[1];
    if (contentType && !contentType.toLowerCase().includes('json')) {
      then.body = draft.bodyText;
    } else {
      try {
        then.body = draft.bodyText.trim() === '' ? null : JSON.parse(draft.bodyText);
      } catch {
        throw new DraftError('The response body is not valid JSON.');
      }
    }
  }
  const list = conditions.map((row) => ({
    source: row.source,
    field: row.field.trim(),
    op: row.op === 'missing' ? 'exists' : row.op,
    value: conditionValue(row),
  }));
  return {
    name: draft.name.trim(),
    route: draft.route,
    priority: draft.priority,
    enabled: draft.enabled,
    when: draft.mode === 'any' ? { any: list } : { all: list },
    then,
  } as RuleIn;
}

export function describeCondition(condition: ConditionLike): string {
  if (isMissing(condition)) return `${condition.source} ${condition.field} is missing`;
  const op = OPERATORS.find((o) => o.value === condition.op)?.label ?? condition.op;
  if (condition.op === 'exists' || condition.op === 'matches_schema') {
    return `${condition.source} ${condition.field} ${op}`;
  }
  return `${condition.source} ${condition.field} ${op} ${valueToText(condition.op, condition.value)}`;
}

export function describeWhen(when: unknown): string {
  const group = when as { all?: ConditionLike[]; any?: ConditionLike[] };
  const list = group.any ?? group.all ?? [];
  if (list.length === 0) return 'Always';
  return list.map(describeCondition).join(group.any ? ' or ' : ' and ');
}

function pathParams(template: string, path: string): Record<string, string> {
  const names: string[] = [];
  const pattern = template.replace(/[.*+?^$()|[\]\\]/g, '\\$&').replace(/\{([^}]+)\}/g, (_, name: string) => {
    names.push(name);
    return '([^/]+)';
  });
  const found = new RegExp(`^${pattern}/?$`).exec(path);
  if (!found) return {};
  return Object.fromEntries(names.map((name, index) => [name, decodeURIComponent(found[index + 1])]));
}

/** "Create rule from this request": conditions that recognise it, returning what it got. */
export function draftFromLog(entry: LogEntry): RuleDraft {
  const route = entry.route_key ?? `${entry.method} ${entry.path.split('?')[0]}`;
  const template = route.slice(route.indexOf(' ') + 1);
  const pathOnly = entry.path.split('?')[0];
  const conditions: ConditionRow[] = [];
  for (const [field, value] of Object.entries(pathParams(template, pathOnly))) {
    conditions.push({ source: 'path', field, op: 'eq', value });
  }
  const query = (entry.request.query ?? []) as [string, string][];
  for (const [field, value] of query) {
    conditions.push({ source: 'query', field, op: 'eq', value });
  }
  const response = entry.response as { body?: string | null; headers?: Record<string, string> };
  const label = conditions.map((c) => `${c.field}=${c.value}`).join(' ');
  return {
    ...emptyDraft(route),
    name: `${entry.status} for ${label || template}`.slice(0, 200),
    priority: 50,
    conditions: conditions.length ? conditions : [],
    status: entry.status || 200,
    bodyMode: response.body ? 'custom' : 'generated',
    bodyText: response.body ?? '',
  };
}

/** Text for a parameter. The server's example honours patterns and formats, so it passes validation. */
export function parameterSample(parameter: { schema?: unknown; example?: unknown }): string {
  const { example } = parameter;
  if (Array.isArray(example)) return example.join(',');
  if (typeof example === 'object' && example !== null) return JSON.stringify(example);
  if (example !== undefined && example !== null) return String(example);
  const node = (parameter.schema ?? {}) as { type?: unknown; enum?: unknown[]; example?: unknown; minimum?: number };
  if (node.example !== undefined) return String(node.example);
  if (Array.isArray(node.enum) && node.enum.length) return String(node.enum[0]);
  const type = Array.isArray(node.type) ? node.type[0] : node.type;
  if (type === 'integer' || type === 'number') return String(node.minimum ?? 1);
  if (type === 'boolean') return 'true';
  return 'sample';
}

export interface SampleRequest {
  method: string;
  path: string;
  query: Record<string, string>;
  headers: Record<string, string>;
  body: unknown;
  /** Conditions the browser cannot satisfy for us, which would make a test misleading. */
  warnings: string[];
}

function setJsonPath(target: Record<string, unknown>, path: string, value: unknown): boolean {
  const keys = path.replace(/^\$\.?/, '').split('.');
  if (keys.some((key) => !/^[\w-]+$/.test(key))) return false;
  let node = target;
  keys.slice(0, -1).forEach((key) => {
    if (typeof node[key] !== 'object' || node[key] === null) node[key] = {};
    node = node[key] as Record<string, unknown>;
  });
  node[keys[keys.length - 1]] = value;
  return true;
}

function satisfying(row: ConditionRow): string | null {
  switch (row.op) {
    case 'eq':
    case 'contains':
      return row.value;
    case 'in':
      return row.value.split(',')[0]?.trim() ?? '';
    case 'neq':
      return `not-${row.value}`;
    case 'gt':
      return String(Number(row.value) + 1);
    case 'lt':
      return String(Number(row.value) - 1);
    case 'exists':
      return 'present';
    default:
      return null;
  }
}

/** A request meant to trigger a rule: spec-required values plus whatever its conditions ask for. */
export function buildSampleRequest(route: RouteDetail, draft: Pick<RuleDraft, 'conditions' | 'mode'>): SampleRequest {
  const pathValues: Record<string, string> = {};
  const query: Record<string, string> = {};
  const headers: Record<string, string> = {};
  const warnings: string[] = [];
  for (const parameter of route.parameters) {
    if (parameter.location === 'path') pathValues[parameter.name] = parameterSample(parameter);
    else if (parameter.required && parameter.location === 'query') query[parameter.name] = parameterSample(parameter);
    else if (parameter.required && parameter.location === 'header') headers[parameter.name] = parameterSample(parameter);
  }
  let body: unknown = route.sample_body ?? undefined;

  const rows = draft.conditions.filter((row) => row.field.trim());
  // "Any" needs just one match, so use a condition we can actually satisfy from here.
  const canSatisfy = (row: ConditionRow) => row.source !== 'cookie' && (row.op === 'missing' || satisfying(row) !== null);
  const chosen = draft.mode === 'any' ? [rows.find(canSatisfy) ?? rows[0]].filter(Boolean) : rows;
  for (const row of chosen) {
    if (row.op === 'missing') continue; // Satisfied by not sending it.
    if (row.op === 'neq' && row.source === 'cookie') continue; // So is this.
    const value = satisfying(row);
    if (value === null) {
      warnings.push(`Can't build a value for ${row.field} (${row.op}); fill it in using Try it.`);
      continue;
    }
    if (row.source === 'path') pathValues[row.field] = value;
    else if (row.source === 'query') query[row.field] = value;
    else if (row.source === 'header') headers[row.field] = value;
    else if (row.source === 'cookie') warnings.push(`Browsers won't let a page set the cookie ${row.field}; send it with curl.`);
    else if (row.source === 'body') {
      const holder = (typeof body === 'object' && body !== null ? { ...(body as object) } : {}) as Record<string, unknown>;
      const typed = row.op === 'gt' || row.op === 'lt' ? Number(value) : value;
      if (setJsonPath(holder, row.field, typed)) body = holder;
      else warnings.push(`Can't build a body for the path ${row.field}; fill it in using Try it.`);
    }
  }
  const path = route.path.replace(/\{([^}]+)\}/g, (_, name: string) =>
    encodeURIComponent(pathValues[name] ?? 'sample'),
  );
  return { method: route.method, path, query, headers, body, warnings };
}
