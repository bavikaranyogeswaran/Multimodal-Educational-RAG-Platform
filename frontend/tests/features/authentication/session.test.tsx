import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it } from 'vitest';

import { RequireAuth } from '@/features/authentication/RequireAuth';
import { SessionProvider } from '@/features/authentication/SessionProvider';
import { useSession } from '@/features/authentication/sessionContext';
import { aSession, createFakeAuth, type FakeAuth } from '../../fixtures/fakeAuth';

/**
 * The session store and the guard in front of protected pages.
 *
 * Most of what is checked here happens in the gaps rather than in the happy path: the
 * moment before the stored session has been read, a change arriving while that read is
 * still in flight, and the point at which one person stops being signed in and the cache
 * still holds their data.
 */

function renderWithSession(
  auth: FakeAuth,
  children: ReactNode,
  { queryClient = new QueryClient(), route = '/' } = {},
) {
  return render(
    <QueryClientProvider client={queryClient}>
      <SessionProvider auth={auth}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </SessionProvider>
    </QueryClientProvider>,
  );
}

function Protected() {
  return <p>the protected page</p>;
}

function guarded() {
  return (
    <Routes>
      <Route
        path="/"
        element={
          <RequireAuth>
            <Protected />
          </RequireAuth>
        }
      />
      <Route path="/sign-in" element={<p>the sign-in screen</p>} />
    </Routes>
  );
}

describe('while the stored session is still being read', () => {
  it('shows neither the page nor the sign-in screen', async () => {
    // The case the third state exists for. Treating not-yet-known as signed-out sends a
    // signed-in person to the sign-in screen on every reload.
    const auth = createFakeAuth({ initial: aSession(), deferInitialRead: true });

    renderWithSession(auth, guarded());

    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.queryByText('the protected page')).not.toBeInTheDocument();
    expect(screen.queryByText('the sign-in screen')).not.toBeInTheDocument();

    auth.releaseInitialRead();
    await waitFor(() => {
      expect(screen.getByText('the protected page')).toBeInTheDocument();
    });
  });
});

describe('once it is known', () => {
  it('renders the page for somebody signed in', async () => {
    const auth = createFakeAuth({ initial: aSession() });

    renderWithSession(auth, guarded());

    await waitFor(() => {
      expect(screen.getByText('the protected page')).toBeInTheDocument();
    });
  });

  it('sends somebody signed out to the sign-in screen', async () => {
    const auth = createFakeAuth({ initial: null });

    renderWithSession(auth, guarded());

    await waitFor(() => {
      expect(screen.getByText('the sign-in screen')).toBeInTheDocument();
    });
  });

  it('treats a session that cannot be read as signed out', async () => {
    // Failing closed costs a sign-in. Failing open would render the application to
    // somebody the server will refuse on every request.
    const auth = createFakeAuth();
    auth.currentSession = () => Promise.reject(new Error('storage unavailable'));

    renderWithSession(auth, guarded());

    await waitFor(() => {
      expect(screen.getByText('the sign-in screen')).toBeInTheDocument();
    });
  });
});

describe('a change arriving while the first read is in flight', () => {
  it('is not undone when that read finishes', async () => {
    // A sign-out that lands before the stored session has been read would otherwise be
    // reversed by the read resolving afterwards, leaving a session on screen that has
    // already ended.
    const auth = createFakeAuth({ initial: aSession(), deferInitialRead: true });

    renderWithSession(auth, guarded());
    act(() => auth.emit(null));

    await waitFor(() => {
      expect(screen.getByText('the sign-in screen')).toBeInTheDocument();
    });

    auth.releaseInitialRead();
    await waitFor(() => {
      expect(screen.queryByText('the protected page')).not.toBeInTheDocument();
    });
  });
});

describe('what the cache holds when the person changes', () => {
  function Reader() {
    const { state } = useSession();
    return <p>{state.status}</p>;
  }

  it('is discarded when a session ends', async () => {
    // Everything fetched belongs to whoever was signed in at the time. Left in place, the
    // next person sees the last one's data rendered from memory while their own request
    // is still in flight.
    const auth = createFakeAuth({ initial: aSession() });
    const queryClient = new QueryClient();
    queryClient.setQueryData(['knowledge-bases'], [{ name: 'Theirs' }]);

    renderWithSession(auth, <Reader />, { queryClient });
    await waitFor(() => expect(screen.getByText('signed-in')).toBeInTheDocument());

    act(() => auth.emit(null));

    await waitFor(() => {
      expect(queryClient.getQueryData(['knowledge-bases'])).toBeUndefined();
    });
  });

  it('is discarded when one person replaces another', async () => {
    const auth = createFakeAuth({ initial: aSession({ userId: 'first' }) });
    const queryClient = new QueryClient();

    renderWithSession(auth, <Reader />, { queryClient });
    await waitFor(() => expect(screen.getByText('signed-in')).toBeInTheDocument());
    queryClient.setQueryData(['knowledge-bases'], [{ name: 'Theirs' }]);

    act(() => auth.emit(aSession({ userId: 'second' })));

    await waitFor(() => {
      expect(queryClient.getQueryData(['knowledge-bases'])).toBeUndefined();
    });
  });

  it('survives a background token refresh for the same person', async () => {
    // Refreshes are frequent and change nothing about who is asking. Clearing on every
    // one would empty the cache every hour for no reason.
    const auth = createFakeAuth({ initial: aSession({ accessToken: 'first' }) });
    const queryClient = new QueryClient();

    renderWithSession(auth, <Reader />, { queryClient });
    await waitFor(() => expect(screen.getByText('signed-in')).toBeInTheDocument());
    queryClient.setQueryData(['knowledge-bases'], [{ name: 'Mine' }]);

    act(() => auth.emit(aSession({ accessToken: 'second' })));

    await waitFor(() => {
      expect(auth.currentSession).toHaveBeenCalled();
    });
    expect(queryClient.getQueryData(['knowledge-bases'])).toEqual([{ name: 'Mine' }]);
  });
});
