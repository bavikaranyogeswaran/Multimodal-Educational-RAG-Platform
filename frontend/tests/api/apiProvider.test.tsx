import { render, screen, waitFor } from '@testing-library/react';
import { useEffect, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { z } from 'zod';

import { ApiProvider } from '@/api/ApiProvider';
import { useApi } from '@/api/apiContext';
import { aSession, createFakeAuth } from '../fixtures/fakeAuth';

/**
 * How the client gets its credential.
 *
 * The behaviour worth pinning down is that it does not keep one. Access tokens last
 * minutes and are refreshed in the background, so a client that reads the token once when
 * it is built signs every later request of a long-lived tab with an expired credential —
 * and the symptom is somebody appearing to be signed out at random.
 */

/** Takes the recorded call loosely: a mock's argument tuple never quite matches fetch's. */
function authorizationOf(call: readonly unknown[] | undefined): string | null {
  const init = call?.[1] as RequestInit | undefined;
  return new Headers(init?.headers).get('Authorization');
}

describe('the credential on each request', () => {
  it('is fetched at the moment of the request, not when the client was built', async () => {
    const auth = createFakeAuth({ initial: aSession({ accessToken: 'first' }) });
    const fetchImpl = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(new Response('{}', { status: 200 })),
    );

    function Caller() {
      const api = useApi();
      const [done, setDone] = useState(0);

      useEffect(() => {
        async function run() {
          await api.request(z.unknown(), '/first');
          // Stands in for a background refresh landing between two requests.
          auth.emit(aSession({ accessToken: 'second' }));
          await api.request(z.unknown(), '/second');
          setDone(2);
        }
        void run();
      }, [api]);

      return <p>{done} done</p>;
    }

    // The provider is given the real client, but the client is given a fetch we can read.
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      fetchImpl as unknown as typeof globalThis.fetch,
    );

    render(
      <ApiProvider auth={auth} baseUrl="">
        <Caller />
      </ApiProvider>,
    );

    await waitFor(() => expect(screen.getByText('2 done')).toBeInTheDocument());

    expect(authorizationOf(fetchImpl.mock.calls[0])).toBe('Bearer first');
    expect(authorizationOf(fetchImpl.mock.calls[1])).toBe('Bearer second');

    vi.restoreAllMocks();
  });

  it('sends no credential when nobody is signed in', async () => {
    const auth = createFakeAuth({ initial: null });
    const fetchImpl = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(new Response('{}', { status: 200 })),
    );
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      fetchImpl as unknown as typeof globalThis.fetch,
    );

    function Caller() {
      const api = useApi();
      useEffect(() => {
        void api.request(z.unknown(), '/anything');
      }, [api]);
      return <p>called</p>;
    }

    render(
      <ApiProvider auth={auth} baseUrl="">
        <Caller />
      </ApiProvider>,
    );

    await waitFor(() => expect(fetchImpl).toHaveBeenCalled());
    expect(authorizationOf(fetchImpl.mock.calls[0])).toBeNull();

    vi.restoreAllMocks();
  });
});

describe('where requests are sent', () => {
  it('stays on this origin when no base is configured', async () => {
    const auth = createFakeAuth({ initial: aSession() });
    const fetchImpl = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(new Response('{}', { status: 200 })),
    );
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      fetchImpl as unknown as typeof globalThis.fetch,
    );

    function Caller() {
      const api = useApi();
      useEffect(() => {
        void api.request(z.unknown(), '/knowledge-bases');
      }, [api]);
      return <p>called</p>;
    }

    render(
      <ApiProvider auth={auth} baseUrl="">
        <Caller />
      </ApiProvider>,
    );

    await waitFor(() => expect(fetchImpl).toHaveBeenCalled());
    expect(fetchImpl.mock.calls[0]?.[0]).toBe('/api/v1/knowledge-bases');

    vi.restoreAllMocks();
  });

  it('goes to the configured host when there is one, without doubling the slash', async () => {
    const auth = createFakeAuth({ initial: aSession() });
    const fetchImpl = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(new Response('{}', { status: 200 })),
    );
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      fetchImpl as unknown as typeof globalThis.fetch,
    );

    function Caller() {
      const api = useApi();
      useEffect(() => {
        void api.request(z.unknown(), '/knowledge-bases');
      }, [api]);
      return <p>called</p>;
    }

    render(
      <ApiProvider auth={auth} baseUrl="https://api.example.com/">
        <Caller />
      </ApiProvider>,
    );

    await waitFor(() => expect(fetchImpl).toHaveBeenCalled());
    expect(fetchImpl.mock.calls[0]?.[0]).toBe('https://api.example.com/api/v1/knowledge-bases');

    vi.restoreAllMocks();
  });
});

describe('using the client without a provider', () => {
  it('says so rather than failing later on a null', () => {
    function Orphan() {
      useApi();
      return null;
    }

    // React logs the thrown error; the assertion is that it is the readable one.
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<Orphan />)).toThrow('outside the API provider');
    consoleError.mockRestore();
  });
});
