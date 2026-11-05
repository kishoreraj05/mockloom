export interface MockRequest {
  method: string;
  path: string;
  query: Record<string, string>;
  headers: Record<string, string>;
  body: unknown;
}

export interface MockResponse {
  status: number;
  statusText: string;
  ms: number;
  rule: string | null;
  source: string | null;
  headers: [string, string][];
  body: string;
}

/** Sends a real request, so it goes through the whole pipeline and shows up in the log. */
export async function sendMockRequest(slug: string, request: MockRequest): Promise<MockResponse> {
  const query = new URLSearchParams(request.query).toString();
  const url = `/mock/${slug}${request.path}${query ? `?${query}` : ''}`;
  const hasBody = !['GET', 'HEAD'].includes(request.method) && request.body !== undefined && request.body !== null;
  const headers: Record<string, string> = { ...request.headers };
  let body: string | undefined;
  if (hasBody) {
    body = typeof request.body === 'string' ? request.body : JSON.stringify(request.body);
    if (!Object.keys(headers).some((name) => name.toLowerCase() === 'content-type')) {
      headers['content-type'] = 'application/json';
    }
  }
  const started = performance.now();
  let response: Response;
  try {
    response = await fetch(url, { method: request.method, headers, body, credentials: 'omit' });
  } catch {
    throw new Error('No response: the connection was dropped. Is a chaos "offline" switch on?');
  }
  const text = await response.text();
  return {
    status: response.status,
    statusText: response.statusText,
    ms: Math.round(performance.now() - started),
    rule: response.headers.get('x-mockforge-rule'),
    source: response.headers.get('x-mockforge-source'),
    headers: [...response.headers.entries()].filter(([name]) => !name.startsWith('x-mockforge-')),
    body: text,
  };
}
