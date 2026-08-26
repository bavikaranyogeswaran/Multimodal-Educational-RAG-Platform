import { createContext, useContext } from 'react';

import type { KnowledgeBaseGateway } from '@/features/knowledge-bases/gateway';

export const KnowledgeBaseContext = createContext<KnowledgeBaseGateway | null>(null);

export function useKnowledgeBaseGateway(): KnowledgeBaseGateway {
  const ctx = useContext(KnowledgeBaseContext);
  if (!ctx) {
    throw new Error('useKnowledgeBaseGateway must be used within KnowledgeBaseProvider');
  }
  return ctx;
}
