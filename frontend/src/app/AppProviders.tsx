import { QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { BrowserRouter } from 'react-router';

import { ApiProvider } from '@/api/ApiProvider';
import { createQueryClient } from '@/app/queryClient';
import { SessionProvider } from '@/features/authentication/SessionProvider';
import type { AuthGateway } from '@/features/authentication/gateway';
import { DocumentProvider } from '@/features/documents/DocumentProvider';
import type { DocumentGateway } from '@/features/documents/gateway';
import type { KnowledgeBaseGateway } from '@/features/knowledge-bases/gateway';
import { KnowledgeBaseProvider } from '@/features/knowledge-bases/KnowledgeBaseProvider';

interface AppProvidersProps {
  /** Passed in rather than built here, so what a test runs against is its own. */
  auth: AuthGateway;
  apiBaseUrl: string;
  children: ReactNode;
  /** Substituted in tests for a router that does not touch the address bar. */
  router?: (children: ReactNode) => ReactNode;
  /** When supplied, bypasses the KB API gateway (for tests that do not want network calls). */
  kbGateway?: KnowledgeBaseGateway;
  /** When supplied, bypasses the document API gateway (for tests that do not want network calls). */
  docGateway?: DocumentGateway;
}

/**
 * Application-wide providers, in the order they depend on each other.
 *
 * The session store sits inside the query client because it clears the cache when the
 * signed-in person changes, and outside the API provider because nothing should be able
 * to make a request before there is somewhere to get a credential from.
 *
 * The client is created in state rather than at module scope so each mount gets its own
 * — otherwise tests would share cache across cases, and the first test to populate the
 * cache would silently change the behaviour of every test after it.
 */
export function AppProviders({
  auth,
  apiBaseUrl,
  children,
  router,
  kbGateway,
  docGateway,
}: AppProvidersProps) {
  const [queryClient] = useState(createQueryClient);
  const wrap = router ?? ((inner: ReactNode) => <BrowserRouter>{inner}</BrowserRouter>);

  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider auth={auth}>
        <ApiProvider auth={auth} baseUrl={apiBaseUrl}>
          <KnowledgeBaseProvider {...(kbGateway !== undefined ? { gateway: kbGateway } : {})}>
            <DocumentProvider {...(docGateway !== undefined ? { gateway: docGateway } : {})}>
              {wrap(children)}
            </DocumentProvider>
          </KnowledgeBaseProvider>
        </ApiProvider>
      </SessionProvider>
    </QueryClientProvider>
  );
}
