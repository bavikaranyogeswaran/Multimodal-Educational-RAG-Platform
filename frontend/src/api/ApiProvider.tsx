import { useMemo, type ReactNode } from 'react';

import { ApiContext } from '@/api/apiContext';
import { ApiClient } from '@/api/client';
import type { AuthGateway } from '@/features/authentication/gateway';

/**
 * One API client for the application, holding a live credential rather than a copy.
 *
 * The token is fetched from the sign-in service on every request instead of being read
 * out of session state when this is built. Access tokens last minutes and are refreshed
 * in the background; a client built once at mount and closed over the token it saw then
 * would sign every request of a long-lived tab with a credential that expired hours ago,
 * and the failure looks like the person being signed out at random.
 */

interface ApiProviderProps {
  auth: AuthGateway;
  baseUrl: string;
  children: ReactNode;
}

export function ApiProvider({ auth, baseUrl, children }: ApiProviderProps) {
  const client = useMemo(
    () =>
      new ApiClient({
        getAccessToken: async () => (await auth.currentSession())?.accessToken ?? null,
        baseUrl,
      }),
    [auth, baseUrl],
  );

  return <ApiContext.Provider value={client}>{children}</ApiContext.Provider>;
}
