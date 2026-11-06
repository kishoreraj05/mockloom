import createClient from 'openapi-fetch';
import type { components, paths } from './schema';

type Schemas = components['schemas'];
export type WorkspaceOut = Schemas['WorkspaceOut'];
export type RouteSummary = Schemas['RouteSummary'];
export type RouteDetail = Schemas['RouteDetail'];
export type ResponseSample = Schemas['ResponseSample'];
export type RuleIn = Schemas['RuleIn'];
export type RuleOut = Schemas['RuleOut'];
export type ChaosIn = Schemas['ChaosIn'];
export type ChaosOut = Schemas['ChaosOut'];
export type LogEntry = Schemas['LogEntry'];
export type SpecIssue = Schemas['SpecIssueOut'];
export type SpecValidation = Schemas['SpecValidation'];
export type SpecSaved = Schemas['SpecSaved'];

export const api = createClient<paths>({ baseUrl: '' });

export class ApiError extends Error {
  constructor(
    message: string,
    readonly issues: SpecIssue[] = [],
  ) {
    super(message);
  }
}

type FastApiError = { detail?: unknown };

function toApiError(error: unknown): ApiError {
  const detail = (error as FastApiError)?.detail;
  if (typeof detail === 'string') return new ApiError(detail);
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: string; loc?: unknown[] };
    const where = first?.loc?.slice(1).join('.');
    return new ApiError(where ? `${where}: ${first?.msg}` : (first?.msg ?? 'Invalid request'));
  }
  if (detail && typeof detail === 'object') {
    const shaped = detail as { title?: string; issues?: SpecIssue[] };
    return new ApiError(shaped.issues?.[0]?.message ?? shaped.title ?? 'Request failed', shaped.issues ?? []);
  }
  return new ApiError('Could not reach the MockLoom server.');
}

/** Unwraps openapi-fetch's {data, error} so that callers (and TanStack Query) get exceptions. */
export async function unwrap<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await call;
  if (error !== undefined || !response.ok) throw toApiError(error);
  return data as T;
}
