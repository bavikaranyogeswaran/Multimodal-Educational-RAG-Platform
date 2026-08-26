import { useMemo, type ReactNode } from 'react';

import { useApi } from '@/api/apiContext';
import { ApiKnowledgeBaseGateway } from '@/features/knowledge-bases/apiGateway';
import type { KnowledgeBaseGateway } from '@/features/knowledge-bases/gateway';
import { KnowledgeBaseContext } from '@/features/knowledge-bases/gatewayContext';

interface KnowledgeBaseProviderProps {
  /** When supplied (e.g. in tests), skips building the API gateway. */
  gateway?: KnowledgeBaseGateway | undefined;
  children: ReactNode;
}

export function KnowledgeBaseProvider({ gateway, children }: KnowledgeBaseProviderProps) {
  const client = useApi();
  const resolved = useMemo(
    () => gateway ?? new ApiKnowledgeBaseGateway(client),
    [gateway, client],
  );
  return (
    <KnowledgeBaseContext.Provider value={resolved}>{children}</KnowledgeBaseContext.Provider>
  );
}
