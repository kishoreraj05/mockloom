import { describe, expect, it } from 'vitest';
import { absoluteUrl, curlCommand, fetchSnippet, pythonLiteral, pythonSnippet } from './snippets';

const get = { method: 'GET', path: '/a' };
const post = { method: 'POST', path: '/a', query: { q: 'a b' }, headers: { 'x-a': '1' }, body: { n: 1 } };

describe('absoluteUrl', () => {
  it('joins the base, path and encoded query', () => {
    expect(absoluteUrl('http://h/mock/x', get)).toBe('http://h/mock/x/a');
    expect(absoluteUrl('http://h', post)).toBe('http://h/a?q=a+b');
  });
});

describe('curlCommand', () => {
  it('keeps a simple GET simple', () => {
    expect(curlCommand('http://h/mock/x', get)).toBe("curl -i 'http://h/mock/x/a'");
  });

  it('includes the method, query, headers and JSON body', () => {
    expect(curlCommand('http://h', post)).toBe(
      "curl -i -X POST 'http://h/a?q=a+b' -H 'x-a: 1' -H 'content-type: application/json' -d '{\"n\":1}'",
    );
  });

  it('escapes single quotes, so the command is safe to paste', () => {
    expect(curlCommand('http://h', { method: 'POST', path: '/a', body: { t: "it's" } })).toContain(`'{"t":"it'\\''s"}'`);
  });
});

describe('fetchSnippet', () => {
  // These run the snippet for real, against a stand-in fetch.
  async function run(code: string) {
    const calls: [string, RequestInit | undefined][] = [];
    const fakeFetch = async (url: string, init?: RequestInit) => {
      calls.push([url, init]);
      return { status: 200, text: async () => 'ok' };
    };
    const AsyncFunction = Object.getPrototypeOf(async () => undefined).constructor;
    await new AsyncFunction('fetch', 'console', code)(fakeFetch, { log: () => undefined });
    return calls[0];
  }

  it('is valid JavaScript that sends what was asked for', async () => {
    const [url, init] = await run(fetchSnippet('http://h', post));
    expect(url).toBe('http://h/a?q=a+b');
    expect(init?.method).toBe('POST');
    expect(init?.headers).toEqual({ 'x-a': '1', 'content-type': 'application/json' });
    expect(init?.body).toBe('{"n":1}');
  });

  it('leaves out options a plain GET does not need', async () => {
    const [url, init] = await run(fetchSnippet('http://h', get));
    expect(url).toBe('http://h/a');
    expect(init).toBeUndefined();
  });
});

describe('python', () => {
  it('writes True, False and None, not JSON', () => {
    expect(pythonLiteral({ a: true, b: false, c: null })).toBe('{\n    "a": True,\n    "b": False,\n    "c": None,\n}');
  });

  it('handles nesting and empties', () => {
    expect(pythonLiteral({ a: [1, {}] , b: [] })).toBe('{\n    "a": [\n        1,\n        {},\n    ],\n    "b": [],\n}');
  });

  it('sends the method, URL, headers and body', () => {
    const code = pythonSnippet('http://h', post);
    expect(code).toContain('"POST"');
    expect(code).toContain('"http://h/a?q=a+b"');
    expect(code).toContain('headers={');
    expect(code).toContain('json={');
  });
});
