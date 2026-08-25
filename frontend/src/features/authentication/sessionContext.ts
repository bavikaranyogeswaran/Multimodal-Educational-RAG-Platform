import { createContext, useContext } from 'react';

import type { Credentials, Session, SignUpOutcome } from '@/features/authentication/gateway';

/**
 * The session context and the hook that reads it.
 *
 * Kept apart from the provider component so that file exports a component and nothing
 * else, which is what lets the development server hot-replace it without losing state.
 */

/**
 * The state has three cases rather than two, and the third is the one that matters:
 * until the stored session has been read back and refreshed, nobody knows whether
 * anybody is signed in. Collapsing that into signed-out shows the sign-in screen for a
 * moment to a person who is already signed in, and then redirects them away from the
 * page they asked for — a flicker on a fast connection and a wrong destination on a slow
 * one.
 */
export type SessionState =
  { status: 'loading' } | { status: 'signed-in'; session: Session } | { status: 'signed-out' };

export interface SessionContextValue {
  state: SessionState;
  signIn: (credentials: Credentials) => Promise<void>;
  signUp: (credentials: Credentials) => Promise<SignUpOutcome>;
  signOut: () => Promise<void>;
}

export const SessionContext = createContext<SessionContextValue | null>(null);

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error('useSession was called outside the session provider.');
  }
  return value;
}
