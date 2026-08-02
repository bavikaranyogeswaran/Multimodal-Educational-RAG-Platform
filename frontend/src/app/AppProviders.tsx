import { QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

import { createQueryClient } from '@/app/queryClient';

interface AppProvidersProps {
  children: ReactNode;
}

/**
 * Application-wide providers.
 *
 * The client is created in state rather than at module scope so each mount gets its own
 * — otherwise tests would share cache across cases, and the first test to populate the
 * cache would silently change the behaviour of every test after it.
 */
export function AppProviders({ children }: AppProvidersProps) {
  const [queryClient] = useState(createQueryClient);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
