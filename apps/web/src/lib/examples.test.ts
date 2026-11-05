import { describe, expect, it } from 'vitest';
import { EXAMPLES, exampleRules, exampleSpec } from './examples';

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
