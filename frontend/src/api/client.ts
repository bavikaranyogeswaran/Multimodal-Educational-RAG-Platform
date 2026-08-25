import type { ZodType } from 'zod';

import { ApiError, ContractViolationError, NetworkError } from '@/api/errors';
import { errorBody, fieldPath, type ValidationIssue } from '@/schemas/errors';

/**
 * The one place a request leaves this application.
 *
 * Everything that reaches a screen passes through here and is parsed against the schema
 * the caller names, so a component receives a value the contract has already vouched for
 * rather than one the type system was merely told to believe in. The alternative — a
 * typed fetch that casts — is the same code with the checking removed, and it fails at
 * the point of use, several screens away from the mismatch that caused it.
 *
 * Authentication is injected rather than imported. The client knows it needs a token and
 * knows nothing about where tokens come from, which keeps the sign-in provider out of
 * every test that wants to assert about a request.
 */

/** Where every route lives. Same-origin in development through the dev server's proxy. */
export const API_PREFIX = '/api/v1';

/** Echoed on every response, including ones whose body carries no trace id of its own. */
const TRACE_HEADER = 'X-Trace-ID';

export type AccessTokenProvider = () => string | null | Promise<string | null>;

export interface ApiClientOptions {
  /** Returns the current access token, or null when nobody is signed in. */
  getAccessToken?: AccessTokenProvider;
  /**
   * Where the API lives, when it is not this origin. Empty is the normal case: requests
   * stay origin-relative, which is what the development proxy and a single-origin
   * deployment both want. Setting it is what makes the trace header cross an origin
   * boundary, and therefore what the server has to expose it for.
   */
  baseUrl?: string;
  /** Overridden in tests; defaults to the global fetch. */
  fetch?: typeof globalThis.fetch;
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  /** Sent as JSON. Pass a FormData instead to send a file. */
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  signal?: AbortSignal;
}

export class ApiClient {
  readonly #getAccessToken: AccessTokenProvider;
  readonly #baseUrl: string;
  readonly #fetch: typeof globalThis.fetch;

  constructor(options: ApiClientOptions = {}) {
    this.#getAccessToken = options.getAccessToken ?? (() => null);
    // A trailing slash here and a leading one on the prefix would produce a double
    // slash, which some servers route differently and others reject outright.
    this.#baseUrl = (options.baseUrl ?? '').replace(/\/+$/, '');
    // Bound to globalThis: an unbound window.fetch throws an illegal invocation error.
    this.#fetch = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  /** Send a request and return its body parsed against `schema`. */
  async request<T>(schema: ZodType<T>, path: string, options: RequestOptions = {}): Promise<T> {
    const response = await this.#send(path, options);
    const payload = await this.#readJson(response, path);

    const parsed = schema.safeParse(payload);
    if (!parsed.success) {
      throw new ContractViolationError(path, describeParseFailure(parsed.error.issues));
    }
    return parsed.data;
  }

  /**
   * Send a request that answers with no body.
   *
   * Deletes return 204, and asking for JSON that was never sent would fail every one of
   * them at the parse rather than at the request.
   */
  async requestNoContent(path: string, options: RequestOptions = {}): Promise<void> {
    await this.#send(path, options);
  }

  // -----------------------------------------------------------------------

  async #send(path: string, options: RequestOptions): Promise<Response> {
    const token = await this.#getAccessToken();
    const headers = new Headers({ Accept: 'application/json' });
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }

    const init: RequestInit = { method: options.method ?? 'GET', headers };
    if (options.signal) {
      init.signal = options.signal;
    }
    if (options.body !== undefined) {
      if (options.body instanceof FormData) {
        // Deliberately no content type: the browser has to set it, because only the
        // browser knows the multipart boundary it is about to generate.
        init.body = options.body;
      } else {
        headers.set('Content-Type', 'application/json');
        init.body = JSON.stringify(options.body);
      }
    }

    let response: Response;
    try {
      response = await this.#fetch(
        `${this.#baseUrl}${API_PREFIX}${path}${buildQuery(options.query)}`,
        init,
      );
    } catch (cause) {
      throw new NetworkError(path, cause);
    }

    if (!response.ok) {
      throw await toApiError(response, path);
    }
    return response;
  }

  async #readJson(response: Response, path: string): Promise<unknown> {
    if (response.status === 204) {
      return undefined;
    }
    try {
      return await response.json();
    } catch {
      throw new ContractViolationError(path, 'the body was not valid JSON');
    }
  }
}

// ---------------------------------------------------------------------------

function buildQuery(query: RequestOptions['query']): string {
  if (!query) {
    return '';
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) {
      params.set(key, String(value));
    }
  }
  const rendered = params.toString();
  return rendered ? `?${rendered}` : '';
}

/**
 * Turn a refusal into an error carrying everything that can be recovered from it.
 *
 * The trace id is read from the header rather than the body, because the header is on
 * every response and the body's copy is not: a validation failure answers before the
 * application is reached and carries no trace id at all, and a failure that returned no
 * JSON has no body to read. Taking it from the header means an error can always be quoted
 * back to whoever has the server logs.
 */
async function toApiError(response: Response, path: string): Promise<ApiError> {
  const traceId = response.headers.get(TRACE_HEADER);

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = undefined;
  }

  const parsed = errorBody.safeParse(payload);
  if (!parsed.success) {
    // A proxy's HTML error page, or an empty body. Nothing to quote, so say what is known.
    return new ApiError(
      response.status,
      `Request to ${path} failed with status ${response.status}`,
      traceId,
    );
  }

  const { detail } = parsed.data;
  if (typeof detail === 'string') {
    return new ApiError(response.status, detail, traceId ?? null);
  }
  return new ApiError(response.status, summariseIssues(detail), traceId, detail);
}

/** Per-field problems as one sentence, for a place that has room for only one. */
function summariseIssues(issues: readonly ValidationIssue[]): string {
  if (issues.length === 0) {
    return 'The request was rejected as invalid.';
  }
  return issues.map((issue) => `${fieldPath(issue) || 'request'}: ${issue.msg}`).join('; ');
}

/** Where the response stopped matching, named by field rather than by position. */
function describeParseFailure(
  issues: readonly { path: PropertyKey[]; message: string }[],
): string {
  return issues
    .map((issue) => `${issue.path.map(String).join('.') || 'response'} ${issue.message}`)
    .join('; ');
}
