import { describe, expect, it } from 'vitest';
import type { LogEntry, RouteDetail, RuleOut } from '@/api/client';
import { buildSampleRequest, describeWhen, draftFromLog, draftFromRule, draftToRule, DraftError, emptyDraft } from './rules';

const route = {
  key: 'GET /pets/{id}',
  method: 'GET',
  path: '/pets/{id}',
  parameters: [
    { name: 'id', location: 'path', required: true, schema: { type: 'integer' } },
    { name: 'page', location: 'query', required: true, schema: { type: 'integer', minimum: 1 } },
    { name: 'opt', location: 'query', required: false, schema: { type: 'string' } },
  ],
  sample_body: null,
} as unknown as RouteDetail;

function draft(overrides = {}) {
  return { ...emptyDraft('GET /pets'), name: 'Rule', ...overrides };
}

describe('draftToRule', () => {
  it('leaves the body out when it should be generated', () => {
    const rule = draftToRule(draft({ bodyMode: 'generated', bodyText: '{"ignored":1}' }));
    expect('body' in (rule.then as object)).toBe(false);
  });

  it('parses a JSON body and keeps templates inside it', () => {
    const rule = draftToRule(draft({ bodyMode: 'custom', bodyText: '{"id":"{{request.path.id}}"}' }));
    expect((rule.then as { body: unknown }).body).toEqual({ id: '{{request.path.id}}' });
  });

  it('refuses invalid JSON unless the content type says it is not JSON', () => {
    expect(() => draftToRule(draft({ bodyMode: 'custom', bodyText: '{oops' }))).toThrow(DraftError);
    const rule = draftToRule(
      draft({ bodyMode: 'custom', bodyText: '<xml/>', headers: [{ name: 'Content-Type', value: 'text/xml' }] }),
    );
    expect((rule.then as { body: unknown }).body).toBe('<xml/>');
  });

  it('types condition values by operator and skips blank rows', () => {
    const rule = draftToRule(
      draft({
        conditions: [
          { source: 'header', field: 'x-tier', op: 'in', value: 'free, trial' },
          { source: 'query', field: 'n', op: 'gt', value: '5' },
          { source: 'query', field: 'q', op: 'exists', value: 'ignored' },
          { source: 'query', field: '  ', op: 'eq', value: 'blank row' },
        ],
      }),
    );
    expect((rule.when as { all: { value: unknown }[] }).all.map((c) => c.value)).toEqual([['free', 'trial'], 5, null]);
  });

  it('needs a name and valid numbers', () => {
    expect(() => draftToRule(draft({ name: ' ' }))).toThrow(/name/);
    expect(() =>
      draftToRule(draft({ conditions: [{ source: 'query', field: 'n', op: 'gt', value: 'abc' }] })),
    ).toThrow(/number/);
  });

  it('uses "any" when asked', () => {
    expect('any' in (draftToRule(draft({ mode: 'any' })).when as object)).toBe(true);
  });
});

describe('draftFromRule', () => {
  it('round-trips through the API shape', () => {
    const original = draft({
      priority: 7,
      status: 404,
      bodyMode: 'custom',
      bodyText: '{\n  "a": 1\n}',
      delayMs: 300,
      headers: [{ name: 'x-a', value: 'b' }],
      conditions: [{ source: 'header', field: 'x-tier', op: 'in', value: 'free, trial' }],
    });
    const api = draftToRule(original);
    const back = draftFromRule({ ...api, id: 'r1', orphaned: false } as unknown as RuleOut);
    expect(back).toEqual({ ...original, id: 'r1' });
  });

  it('keeps "is missing" from turning into "exists" when a rule is re-saved', () => {
    const stored = {
      id: 'r',
      orphaned: false,
      name: 'No key',
      route: 'GET /balance',
      priority: 10,
      enabled: true,
      when: { all: [{ source: 'header', field: 'authorization', op: 'exists', value: false }] },
      then: { status: 401 },
    } as unknown as RuleOut;
    const form = draftFromRule(stored);
    expect(form.conditions[0].op).toBe('missing');
    expect((draftToRule(form).when as { all: unknown[] }).all[0]).toEqual({
      source: 'header',
      field: 'authorization',
      op: 'exists',
      value: false,
    });
  });

  it('keeps a generated body generated', () => {
    const api = draftToRule(draft({ status: 404, bodyMode: 'generated' }));
    expect(draftFromRule({ ...api, id: 'r', orphaned: false } as unknown as RuleOut).bodyMode).toBe('generated');
  });
});

describe('draftFromLog', () => {
  const entry = {
    method: 'GET',
    path: '/pets/42?status=sold',
    status: 404,
    route_key: 'GET /pets/{id}',
    request: { query: [['status', 'sold']], headers: {}, body: null },
    response: { body: '{"message":"gone"}', headers: {} },
  } as unknown as LogEntry;

  it('builds conditions from the path and query and copies the response', () => {
    const result = draftFromLog(entry);
    expect(result.route).toBe('GET /pets/{id}');
    expect(result.conditions).toEqual([
      { source: 'path', field: 'id', op: 'eq', value: '42' },
      { source: 'query', field: 'status', op: 'eq', value: 'sold' },
    ]);
    expect(result.status).toBe(404);
    expect(result.bodyMode).toBe('custom');
    expect(result.bodyText).toBe('{"message":"gone"}');
  });

  it('falls back to 200 for a dropped request', () => {
    expect(draftFromLog({ ...entry, status: 0 } as LogEntry).status).toBe(200);
  });
});

describe('buildSampleRequest', () => {
  it('fills required parameters from the schema and skips optional ones', () => {
    const sample = buildSampleRequest(route, { mode: 'all', conditions: [] });
    expect(sample.path).toBe('/pets/1');
    expect(sample.query).toEqual({ page: '1' });
  });

  it('applies conditions so the rule should match', () => {
    const sample = buildSampleRequest(route, {
      mode: 'all',
      conditions: [
        { source: 'path', field: 'id', op: 'eq', value: '999' },
        { source: 'query', field: 'n', op: 'gt', value: '5' },
        { source: 'header', field: 'x-tier', op: 'in', value: 'free, trial' },
        { source: 'body', field: '$.a.b', op: 'eq', value: 'x' },
      ],
    });
    expect(sample.path).toBe('/pets/999');
    expect(sample.query.n).toBe('6');
    expect(sample.headers['x-tier']).toBe('free');
    expect(sample.body).toEqual({ a: { b: 'x' } });
  });

  it('says so when a condition cannot be met from the browser', () => {
    const sample = buildSampleRequest(route, {
      mode: 'all',
      conditions: [
        { source: 'cookie', field: 'role', op: 'eq', value: 'admin' },
        { source: 'query', field: 'q', op: 'regex', value: '^a' },
      ],
    });
    expect(sample.warnings).toHaveLength(2);
  });

  it('satisfies "is missing" by leaving the value out, with no warning', () => {
    const sample = buildSampleRequest(route, {
      mode: 'all',
      conditions: [{ source: 'header', field: 'authorization', op: 'missing', value: '' }],
    });
    expect(sample.headers.authorization).toBeUndefined();
    expect(sample.warnings).toEqual([]);
  });

  it('uses the example from the server, which fits patterns the schema asks for', () => {
    const withExample = {
      ...route,
      parameters: [{ name: 'id', location: 'path', required: true, schema: { type: 'string' }, example: 'cus_ab12' }],
    } as unknown as RouteDetail;
    expect(buildSampleRequest(withExample, { mode: 'all', conditions: [] }).path).toBe('/pets/cus_ab12');
  });

  it('satisfies "cookie does not equal" by not sending the cookie', () => {
    const sample = buildSampleRequest(route, {
      mode: 'all',
      conditions: [{ source: 'cookie', field: 'role', op: 'neq', value: 'admin' }],
    });
    expect(sample.warnings).toEqual([]);
  });

  it('in "any" mode, prefers a condition it can satisfy over a cookie', () => {
    const sample = buildSampleRequest(route, {
      mode: 'any',
      conditions: [
        { source: 'cookie', field: 'role', op: 'eq', value: 'admin' },
        { source: 'header', field: 'x-admin', op: 'exists', value: '' },
      ],
    });
    expect(sample.headers['x-admin']).toBe('present');
    expect(sample.warnings).toEqual([]);
  });

  it('only needs one condition in "any" mode', () => {
    const sample = buildSampleRequest(route, {
      mode: 'any',
      conditions: [
        { source: 'query', field: 'a', op: 'eq', value: '1' },
        { source: 'query', field: 'b', op: 'eq', value: '2' },
      ],
    });
    expect(sample.query.a).toBe('1');
    expect(sample.query.b).toBeUndefined();
  });
});

describe('describeWhen', () => {
  it('says "is missing" for a condition that wants something absent', () => {
    expect(describeWhen({ all: [{ source: 'header', field: 'authorization', op: 'exists', value: false }] })).toBe(
      'header authorization is missing',
    );
  });

  it('reads like a sentence', () => {
    expect(describeWhen({})).toBe('Always');
    expect(describeWhen({ all: [{ source: 'query', field: 'a', op: 'eq', value: '1' }] })).toBe('query a equals 1');
    expect(
      describeWhen({
        any: [
          { source: 'cookie', field: 'c', op: 'exists' },
          { source: 'header', field: 'h', op: 'in', value: ['x', 'y'] },
        ],
      }),
    ).toBe('cookie c exists or header h is one of x, y');
  });
});
