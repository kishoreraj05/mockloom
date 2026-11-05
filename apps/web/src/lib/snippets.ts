/** Code people can paste into their own project to call a mock. */

export interface SnippetRequest {
  method: string;
  path: string;
  query?: Record<string, string>;
  headers?: Record<string, string>;
  body?: unknown;
}

export type SnippetLanguage = 'curl' | 'javascript' | 'python';

export const SNIPPET_LANGUAGES: { value: SnippetLanguage; label: string }[] = [
  { value: 'curl', label: 'cURL' },
  { value: 'javascript', label: 'JavaScript' },
  { value: 'python', label: 'Python' },
];

export function absoluteUrl(baseUrl: string, request: SnippetRequest): string {
  const query = new URLSearchParams(request.query ?? {}).toString();
  return `${baseUrl}${request.path}${query ? `?${query}` : ''}`;
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

function sendsBody(request: SnippetRequest): boolean {
  return request.body !== undefined && request.body !== null;
}

/** A command that can be pasted into a terminal as is. */
export function curlCommand(baseUrl: string, request: SnippetRequest): string {
  const parts = ['curl', '-i'];
  if (request.method !== 'GET') parts.push('-X', request.method);
  parts.push(shellQuote(absoluteUrl(baseUrl, request)));
  for (const [name, value] of Object.entries(request.headers ?? {})) {
    parts.push('-H', shellQuote(`${name}: ${value}`));
  }
  if (sendsBody(request)) {
    parts.push('-H', shellQuote('content-type: application/json'), '-d', shellQuote(JSON.stringify(request.body)));
  }
  return parts.join(' ');
}

function indentAfterFirstLine(text: string, spaces: number): string {
  return text.replace(/\n/g, `\n${' '.repeat(spaces)}`);
}

export function fetchSnippet(baseUrl: string, request: SnippetRequest): string {
  const headers: Record<string, string> = { ...request.headers };
  if (sendsBody(request)) headers['content-type'] = 'application/json';
  const options: string[] = [];
  if (request.method !== 'GET') options.push(`  method: ${JSON.stringify(request.method)},`);
  if (Object.keys(headers).length) {
    options.push(`  headers: ${indentAfterFirstLine(JSON.stringify(headers, null, 2), 2)},`);
  }
  if (sendsBody(request)) {
    options.push(`  body: JSON.stringify(${indentAfterFirstLine(JSON.stringify(request.body, null, 2), 2)}),`);
  }
  const url = JSON.stringify(absoluteUrl(baseUrl, request));
  const call = options.length ? `await fetch(${url}, {\n${options.join('\n')}\n});` : `await fetch(${url});`;
  return `const response = ${call}\nconsole.log(response.status, await response.text());`;
}

/** Python source for a JSON value. JSON itself won't do: true and null aren't Python. */
export function pythonLiteral(value: unknown, indent = 0): string {
  if (value === null || value === undefined) return 'None';
  if (value === true) return 'True';
  if (value === false) return 'False';
  if (typeof value === 'number' || typeof value === 'string') return JSON.stringify(value);
  const inner = ' '.repeat(indent + 4);
  const close = ' '.repeat(indent);
  if (Array.isArray(value)) {
    if (value.length === 0) return '[]';
    return `[\n${value.map((item) => `${inner}${pythonLiteral(item, indent + 4)},`).join('\n')}\n${close}]`;
  }
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) return '{}';
  const lines = entries.map(([key, item]) => `${inner}${JSON.stringify(key)}: ${pythonLiteral(item, indent + 4)},`);
  return `{\n${lines.join('\n')}\n${close}}`;
}

export function pythonSnippet(baseUrl: string, request: SnippetRequest): string {
  const args = [`    ${JSON.stringify(request.method)},`, `    ${JSON.stringify(absoluteUrl(baseUrl, request))},`];
  if (Object.keys(request.headers ?? {}).length) args.push(`    headers=${pythonLiteral(request.headers, 4)},`);
  if (sendsBody(request)) args.push(`    json=${pythonLiteral(request.body, 4)},`);
  return `import requests\n\nresponse = requests.request(\n${args.join('\n')}\n)\nprint(response.status_code, response.text)`;
}

export function snippet(language: SnippetLanguage, baseUrl: string, request: SnippetRequest): string {
  if (language === 'javascript') return fetchSnippet(baseUrl, request);
  if (language === 'python') return pythonSnippet(baseUrl, request);
  return curlCommand(baseUrl, request);
}
