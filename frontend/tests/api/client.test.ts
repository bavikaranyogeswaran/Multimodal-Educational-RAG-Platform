import { describe, expect, it, vi } from 'vitest';
import { z } from 'zod';

import { ApiClient } from '@/api/client';
import { ApiError, ContractViolationError, NetworkError } from '@/api/errors';
import { knowledgeBase } from '@/schemas/knowledgeBase';
import { domainError, knowledgeBaseFull, validationError } from '../fixtures/backendResponses';

/**
 * The client is the only place a request leaves this application, so what it does with a
 * failure is not a detail — it is the behaviour every screen inherits. These check the
 * three ways a request can fail stay distinguishable, because the response to each is
 * different: show the message, page somebody, or try again.
 */

const TRACE = 'fa3a77ce-b1b9-454d-b868-ffbe477d6367';

function respondWith(
  body: unknown,
  { status = 200, headers = {} }: { status?: number; headers?: Record<string, string> } = {},
): Response {
  const isJson = body !== undefined;
  return new Response(isJson ? JSON.stringify(body) : null, {
    status,
    headers: {
      ...(isJson ? { 'Content-Type': 'application/json' } : {}),
      'X-Trace-ID': TRACE,
      ...headers,
    },
  });
}

/** A fetch that always answers the same way, and remembers how it was called. */
function stubFetch(response: Response) {
  return vi.fn((_url: string, _init?: RequestInit): Promise<Response> =>
    Promise.resolve(response),
  );
}

/**
 * Takes the stub loosely on purpose. A mock's call signature never quite matches the DOM
 * fetch type, and threading that mismatch through every case would put more cast noise in
 * these tests than there is assertion.
 */
function clientWith(fetchImpl: unknown, token: string | null = null) {
  return new ApiClient({
    fetch: fetchImpl as typeof globalThis.fetch,
    getAccessToken: () => token,
  });
}

describe('building the request', () => {
  it('sends every path under the versioned prefix', async () => {
    const fetchImpl = stubFetch(respondWith(knowledgeBaseFull));

    await clientWith(fetchImpl).request(knowledgeBase, '/knowledge-bases/abc');

    expect(fetchImpl.mock.calls[0]?.[0]).toBe('/api/v1/knowledge-bases/abc');
  });

  it('carries the access token when there is one', async () => {
    const fetchImpl = stubFetch(respondWith(knowledgeBaseFull));

    await clientWith(fetchImpl, 'a-token').request(knowledgeBase, '/knowledge-bases/abc');

    const init = fetchImpl.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer a-token');
  });

  it('omits the header entirely when nobody is signed in', async () => {
    // Not an empty bearer: the server would then be refusing a malformed credential
    // rather than answering an anonymous request, and the two need different handling.
    const fetchImpl = stubFetch(respondWith(knowledgeBaseFull));

    await clientWith(fetchImpl, null).request(knowledgeBase, '/knowledge-bases/abc');

    const init = fetchImpl.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).has('Authorization')).toBe(false);
  });

  it('waits for a token that has to be refreshed first', async () => {
    const fetchImpl = stubFetch(respondWith(knowledgeBaseFull));
    const client = new ApiClient({
      fetch: fetchImpl as unknown as typeof globalThis.fetch,
      getAccessToken: () => Promise.resolve('refreshed'),
    });

    await client.request(knowledgeBase, '/knowledge-bases/abc');

    const init = fetchImpl.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer refreshed');
  });

  it('serialises an object body as JSON', async () => {
    const fetchImpl = stubFetch(respondWith(knowledgeBaseFull));

    await clientWith(fetchImpl).request(knowledgeBase, '/knowledge-bases', {
      method: 'POST',
      body: { name: 'New' },
    });

    const init = fetchImpl.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json');
    expect(init.body).toBe('{"name":"New"}');
  });

  it('lets the browser set the content type for a file', async () => {
    // Only the browser knows the multipart boundary it is about to generate. Setting the
    // header by hand produces one without a boundary, and the server cannot read the body.
    const fetchImpl = stubFetch(respondWith(knowledgeBaseFull));
    const form = new FormData();
    form.set('file', new Blob(['x'], { type: 'application/pdf' }), 'book.pdf');

    await clientWith(fetchImpl).request(knowledgeBase, '/documents', {
      method: 'POST',
      body: form,
    });

    const init = fetchImpl.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).has('Content-Type')).toBe(false);
    expect(init.body).toBe(form);
  });

  it('appends query parameters and drops the ones left undefined', async () => {
    const fetchImpl = stubFetch(respondWith(knowledgeBaseFull));

    await clientWith(fetchImpl).request(knowledgeBase, '/documents', {
      query: { knowledge_base_id: 'abc', status: undefined, limit: 20 },
    });

    expect(fetchImpl.mock.calls[0]?.[0]).toBe(
      '/api/v1/documents?knowledge_base_id=abc&limit=20',
    );
  });
});

describe('a response with no body', () => {
  it('resolves without trying to read JSON that was never sent', async () => {
    // Deletes answer 204. Parsing the absent body would fail every one of them.
    const fetchImpl = stubFetch(respondWith(undefined, { status: 204 }));

    await expect(
      clientWith(fetchImpl).requestNoContent('/knowledge-bases/abc', { method: 'DELETE' }),
    ).resolves.toBeUndefined();
  });
});

describe('when the server refuses', () => {
  it('reports the message the application gave, and the trace id', async () => {
    const fetchImpl = stubFetch(respondWith(domainError, { status: 404 }));

    const error = await clientWith(fetchImpl)
      .request(knowledgeBase, '/knowledge-bases/abc')
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
    expect((error as ApiError).message).toBe('Widget not found');
    expect((error as ApiError).traceId).toBe(TRACE);
  });

  it('understands the field-level shape the framework returns', async () => {
    const fetchImpl = stubFetch(respondWith(validationError, { status: 422 }));

    const error = (await clientWith(fetchImpl)
      .request(knowledgeBase, '/conversations', { method: 'POST', body: {} })
      .catch((caught: unknown) => caught)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.issues).toHaveLength(2);
    expect(error.fieldErrors()).toEqual({
      title: 'String should have at least 1 character',
      active_document_id: 'Input should be a valid UUID, invalid character: found `n` at 1',
    });
  });

  it('still recovers the trace id when the body has none', async () => {
    // The framework answers before the application is reached, so its body carries no
    // trace id. The header is on every response, which is why it is read from there.
    const fetchImpl = stubFetch(respondWith(validationError, { status: 422 }));

    const error = (await clientWith(fetchImpl)
      .request(knowledgeBase, '/conversations')
      .catch((caught: unknown) => caught)) as ApiError;

    expect(error.traceId).toBe(TRACE);
  });

  it('does not itself fail when the body is not JSON at all', async () => {
    // A proxy or gateway in front of the application answers in HTML. Throwing while
    // handling the error would replace a 502 with a parse error from this file.
    const fetchImpl = stubFetch(
      new Response('<html>Bad Gateway</html>', {
        status: 502,
        headers: { 'Content-Type': 'text/html' },
      }),
    );

    const error = (await clientWith(fetchImpl)
      .request(knowledgeBase, '/knowledge-bases')
      .catch((caught: unknown) => caught)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(502);
    expect(error.message).toContain('502');
  });

  it('knows which refusals are worth repeating', () => {
    expect(new ApiError(500, 'x', null).isRetryable).toBe(true);
    expect(new ApiError(429, 'x', null).isRetryable).toBe(true);
    // A Knowledge Base somebody else owns answers 404 by design and always will.
    expect(new ApiError(404, 'x', null).isRetryable).toBe(false);
    expect(new ApiError(401, 'x', null).isRetryable).toBe(false);
  });
});

describe('when the answer does not match the contract', () => {
  it('fails distinctly from a refusal, naming the field that moved', async () => {
    const fetchImpl = stubFetch(
      respondWith({ ...knowledgeBaseFull, active_index_version: 'two' }),
    );

    const error = await clientWith(fetchImpl)
      .request(knowledgeBase, '/knowledge-bases/abc')
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ContractViolationError);
    expect(error).not.toBeInstanceOf(ApiError);
    expect((error as ContractViolationError).message).toContain('active_index_version');
  });

  it('treats a successful response carrying nonsense as a contract failure', async () => {
    const fetchImpl = stubFetch(
      new Response('not json at all', { status: 200, headers: { 'X-Trace-ID': TRACE } }),
    );

    const error = await clientWith(fetchImpl)
      .request(knowledgeBase, '/knowledge-bases/abc')
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ContractViolationError);
  });

  it('accepts a response that satisfies the schema it was given', async () => {
    const fetchImpl = stubFetch(respondWith(knowledgeBaseFull));

    const parsed = await clientWith(fetchImpl).request(knowledgeBase, '/knowledge-bases/abc');

    expect(parsed.name).toBe('Cloud Data Science');
    expect(parsed.created_at).toBeInstanceOf(Date);
  });
});

describe('when the request never arrives', () => {
  it('reports a network failure rather than the browser stack behind it', async () => {
    const fetchImpl = vi.fn((_url: string, _init?: RequestInit): Promise<Response> =>
      Promise.reject(new TypeError('Failed to fetch')),
    );

    const error = await clientWith(fetchImpl)
      .request(knowledgeBase, '/knowledge-bases')
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(NetworkError);
    expect((error as NetworkError).cause).toBeInstanceOf(TypeError);
  });
});

describe('a schema that expects nothing in particular', () => {
  it('still parses, so a caller can opt out without bypassing the client', async () => {
    const fetchImpl = stubFetch(respondWith({ anything: true }));

    const parsed = await clientWith(fetchImpl).request(z.unknown(), '/whatever');

    expect(parsed).toEqual({ anything: true });
  });
});
