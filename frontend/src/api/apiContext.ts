import { createContext, useContext } from 'react';

import type { ApiClient } from '@/api/client';

/**
 * The API context and the hook that reads it, kept apart from the provider component so
 * that file exports a component and nothing else.
 */

export const ApiContext = createContext<ApiClient | null>(null);

export function useApi(): ApiClient {
  const client = useContext(ApiContext);
  if (!client) {
    throw new Error('useApi was called outside the API provider.');
  }
  return client;
}
