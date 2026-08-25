import { QueryClient } from '@tanstack/react-query';

import { ApiError, ContractViolationError } from '@/api/errors';

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
          // A response the schemas reject is a deployment problem: the two sides of the
          // contract have moved apart, so the same request produces the same unreadable
          // answer. Retrying turns one loud failure into three quiet ones.
          if (error instanceof ContractViolationError) {
            return false;
          }
          // A refusal is worth repeating only where the server suggested it might answer
          // differently. A Knowledge Base somebody else owns answers 404 by design and
          // always will, so retrying it is pure latency.
          if (error instanceof ApiError) {
            return error.isRetryable && failureCount < 2;
          }
          // Anything left never reached a server. Those are worth another go.
          return failureCount < 2;
        },
      },
      mutations: {
        retry: false,
      },
    },
  });
}
