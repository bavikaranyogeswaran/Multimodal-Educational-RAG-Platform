import { vi } from 'vitest';

import {
  AuthenticationFailure,
  type AuthGateway,
  type Credentials,
  type Session,
  type SignUpOutcome,
} from '@/features/authentication/gateway';

/**
 * A sign-in service under the test's control.
 *
 * The reason for a stand-in rather than the real SDK is timing. What is worth testing
 * here is what happens in the gaps — before the stored session has been read back, when
 * a token is refreshed behind the application's back, when a change arrives while the
 * first read is still in flight — and none of those are reachable against a real service
 * without waiting on it.
 */

export const aSession = (overrides: Partial<Session> = {}): Session => ({
  accessToken: 'token-1',
  userId: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
  email: 'student@example.com',
  ...overrides,
});

export interface FakeAuth extends AuthGateway {
  /** Push a session change, as a background refresh or another tab would. */
  emit(session: Session | null): void;
  /** Let a deferred first read finish, so the loading state can be observed first. */
  releaseInitialRead(): void;
  /** What the next sign-in does. */
  nextSignIn: { session?: Session; failure?: string };
  nextSignUp: { outcome?: SignUpOutcome; failure?: string };
  signInCalls: { email: string; password: string }[];
}

export function createFakeAuth(
  options: { initial?: Session | null; deferInitialRead?: boolean } = {},
): FakeAuth {
  const listeners = new Set<(session: Session | null) => void>();
  let current: Session | null = options.initial ?? null;

  let release = (): void => {};
  const firstRead = options.deferInitialRead
    ? new Promise<void>((resolve) => {
        release = resolve;
      })
    : Promise.resolve();

  const auth: FakeAuth = {
    nextSignIn: {},
    nextSignUp: { outcome: 'signed-in' },
    signInCalls: [],

    currentSession: vi.fn(async () => {
      await firstRead;
      return current;
    }),

    onChange(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },

    signIn: vi.fn(async ({ email, password }: Credentials) => {
      auth.signInCalls.push({ email, password });
      await Promise.resolve();
      if (auth.nextSignIn.failure) {
        throw new AuthenticationFailure(auth.nextSignIn.failure);
      }
      current = auth.nextSignIn.session ?? aSession();
      return current;
    }),

    signUp: vi.fn(async () => {
      await Promise.resolve();
      if (auth.nextSignUp.failure) {
        throw new AuthenticationFailure(auth.nextSignUp.failure);
      }
      return auth.nextSignUp.outcome ?? 'signed-in';
    }),

    signOut: vi.fn(async () => {
      await Promise.resolve();
      current = null;
    }),

    emit(session) {
      current = session;
      for (const listener of listeners) {
        listener(session);
      }
    },

    releaseInitialRead() {
      release();
    },
  };

  return auth;
}
