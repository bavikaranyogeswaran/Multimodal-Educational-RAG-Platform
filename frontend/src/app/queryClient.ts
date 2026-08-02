import { QueryClient } from '@tanstack/react-query';

/**
 * Shared server-state client.
 *
 * Defaults are deliberately conservative: this application's data is either slow-moving
 * (Knowledge Bases, documents) or explicitly invalidated after a mutation. Aggressive
 * refetching would re-request expensive retrieval endpoints for no benefit.
 *
 * Document processing status is the exception — it polls, and sets its own interval at
 * the call site.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          // Never retry an authorization failure. A Knowledge Base the user does not own
          // returns 404 by design, so it will never succeed and retrying is pure latency.
          if (error instanceof Response && (error.status === 401 || error.status === 404)) {
            return false;
          }
          return failureCount < 2;
        },
      },
      mutations: {
        retry: false,
      },
    },
  });
}
