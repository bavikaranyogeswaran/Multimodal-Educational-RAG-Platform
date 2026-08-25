import { createClient, type Session as SupabaseSession } from '@supabase/supabase-js';

import type { AppEnv } from '@/app/env';
import {
  AuthenticationFailure,
  type AuthGateway,
  type Credentials,
  type Session,
  type SignUpOutcome,
} from '@/features/authentication/gateway';

/**
 * The sign-in service, behind the interface the rest of the application talks to.
 *
 * This is the only module that imports the vendor SDK.
 */

/**
 * Taken from the factory rather than written out. The SDK's client type carries five
 * generic parameters whose defaults differ between the constructor and the exported type,
 * so naming it by hand produces a type that is subtly not what `createClient` returns.
 */
type BrowserSupabaseClient = ReturnType<typeof createClient>;

function toSession(session: SupabaseSession | null): Session | null {
  if (!session) {
    return null;
  }
  return {
    accessToken: session.access_token,
    userId: session.user.id,
    email: session.user.email ?? null,
  };
}

export function createSupabaseAuthGateway(client: BrowserSupabaseClient): AuthGateway {
  return {
    async currentSession() {
      // Refreshes the token when it is close to expiring, which is why this is asked
      // again on every request rather than answered once and remembered.
      const { data, error } = await client.auth.getSession();
      if (error) {
        throw new AuthenticationFailure(error.message);
      }
      return toSession(data.session);
    },

    onChange(listener) {
      const { data } = client.auth.onAuthStateChange((_event, session) => {
        listener(toSession(session));
      });
      return () => {
        data.subscription.unsubscribe();
      };
    },

    async signIn({ email, password }: Credentials) {
      const { data, error } = await client.auth.signInWithPassword({ email, password });
      if (error) {
        throw new AuthenticationFailure(error.message);
      }
      const session = toSession(data.session);
      if (!session) {
        throw new AuthenticationFailure('Signing in did not produce a session.');
      }
      return session;
    },

    async signUp({ email, password }: Credentials): Promise<SignUpOutcome> {
      const { data, error } = await client.auth.signUp({ email, password });
      if (error) {
        throw new AuthenticationFailure(error.message);
      }
      // A project that verifies email addresses accepts the registration and returns no
      // session. That is a success with something still to do, not a failure.
      return data.session ? 'signed-in' : 'confirmation-required';
    },

    async signOut() {
      const { error } = await client.auth.signOut();
      if (error) {
        throw new AuthenticationFailure(error.message);
      }
    },
  };
}

export function createSupabaseClient(env: AppEnv): BrowserSupabaseClient {
  return createClient(env.supabaseUrl, env.supabaseAnonKey, {
    auth: {
      persistSession: true,
      // Kept on deliberately: without it a tab left open overnight holds an expired token
      // and every request fails as unauthorised until the page is reloaded.
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  });
}
