import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import type { AuthGateway, Credentials, Session } from '@/features/authentication/gateway';
import {
  SessionContext,
  type SessionContextValue,
  type SessionState,
} from '@/features/authentication/sessionContext';

/** Who is signed in, for the whole application. */

function toState(session: Session | null): SessionState {
  return session ? { status: 'signed-in', session } : { status: 'signed-out' };
}

interface SessionProviderProps {
  auth: AuthGateway;
  children: ReactNode;
}

export function SessionProvider({ auth, children }: SessionProviderProps) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<SessionState>({ status: 'loading' });

  useEffect(() => {
    let active = true;
    // Whether anything more recent than the initial read has already arrived. Without
    // this, a sign-out that happens while the first read is still in flight is undone by
    // that read resolving afterwards, leaving the application showing a session that has
    // already ended.
    let superseded = false;

    void auth.currentSession().then(
      (session) => {
        if (active && !superseded) {
          setState(toState(session));
        }
      },
      () => {
        // A stored session that cannot be read is not a signed-in one. Failing closed
        // here costs a sign-in; failing open would render the application to nobody.
        if (active && !superseded) {
          setState({ status: 'signed-out' });
        }
      },
    );

    const unsubscribe = auth.onChange((session) => {
      superseded = true;
      if (active) {
        setState(toState(session));
      }
    });

    return () => {
      active = false;
      unsubscribe();
    };
  }, [auth]);

  // Everything fetched so far belongs to whoever was signed in when it was fetched. When
  // that stops being true — a sign-out, an expiry, one person handing the laptop to
  // another — the cache has to go, or the next person sees the last one's Knowledge Bases
  // rendered from memory while their own request is still in flight.
  const lastUserId = useRef<string | null>(null);
  useEffect(() => {
    if (state.status === 'loading') {
      return;
    }
    const userId = state.status === 'signed-in' ? state.session.userId : null;
    if (lastUserId.current !== null && lastUserId.current !== userId) {
      queryClient.clear();
    }
    lastUserId.current = userId;
  }, [state, queryClient]);

  const signIn = useCallback(
    async (credentials: Credentials) => {
      const session = await auth.signIn(credentials);
      setState(toState(session));
    },
    [auth],
  );

  const signUp = useCallback((credentials: Credentials) => auth.signUp(credentials), [auth]);

  const signOut = useCallback(async () => {
    await auth.signOut();
    setState({ status: 'signed-out' });
  }, [auth]);

  const value = useMemo<SessionContextValue>(
    () => ({ state, signIn, signUp, signOut }),
    [state, signIn, signUp, signOut],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
