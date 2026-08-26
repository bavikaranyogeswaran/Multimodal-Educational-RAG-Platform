import { createContext, useContext } from 'react';

import type { DocumentGateway } from '@/features/documents/gateway';

export const DocumentContext = createContext<DocumentGateway | null>(null);

export function useDocumentGateway(): DocumentGateway {
  const ctx = useContext(DocumentContext);
  if (!ctx) throw new Error('useDocumentGateway must be used within DocumentProvider');
  return ctx;
}
