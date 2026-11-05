import { describe, expect, it } from 'vitest';
import { curlCommand, EXAMPLES, exampleRules, exampleSpec, type Scenario } from './examples';

const scenario = (extra: Partial<Scenario>): Scenario => ({
  label: 'x',
  method: 'GET',
  path: '/a',
  expect_status: 200,
  expect_rule: null,
  ...extra,
});

describe('example files', () => {
  it('every catalog entry has its spec and rules bundled', () => {
    expect(EXAMPLES.length).toBeGreaterThanOrEqual(4);
    for (const example of EXAMPLES) {
      expect(exampleSpec(example.id)).toContain('openapi:');
      expect(exampleRules(example.id).length).toBeGreaterThan(0);
    }
  });

  it("doesn't confuse one example's rules with another's", () => {
    const names = exampleRules('payments').map((rule) => rule.name);
    expect(names).toContain('Card declined');
    expect(names).not.toContain('Empty list');
  });
});

describe('curlCommand', () => {
  it('keeps a simple GET simple', () => {
    expect(curlCommand('http://h/mock/x', scenario({}))).toBe("curl -i 'http://h/mock/x/a'");
  });

  it('includes the method, query, headers and JSON body', () => {
    const command = curlCommand(
      'http://h',
      scenario({ method: 'POST', query: { q: 'a b' }, headers: { 'x-a': '1' }, body: { n: 1 } }),
    );
    expect(command).toBe(
      "curl -i -X POST 'http://h/a?q=a+b' -H 'x-a: 1' -H 'content-type: application/json' -d '{\"n\":1}'",
    );
  });

  it('escapes single quotes, so the command is safe to paste', () => {
    expect(curlCommand('http://h', scenario({ method: 'POST', body: { t: "it's" } }))).toContain(`'{"t":"it'\\''s"}'`);
  });
});
