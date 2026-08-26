import { useMemo, type ReactNode } from 'react';

import { useApi } from '@/api/apiContext';
import { ApiDocumentGateway } from '@/features/documents/apiGateway';
import type { DocumentGateway } from '@/features/documents/gateway';
import { DocumentContext } from '@/features/documents/gatewayContext';

interface DocumentProviderProps {
  /** When supplied (e.g. in tests), skips building the API gateway. */
  gateway?: DocumentGateway | undefined;
  children: ReactNode;
}

export function DocumentProvider({ gateway, children }: DocumentProviderProps) {
  const client = useApi();
  const resolved = useMemo(
    () => gateway ?? new ApiDocumentGateway(client),
    [gateway, client],
  );
  return <DocumentContext.Provider value={resolved}>{children}</DocumentContext.Provider>;
}
