import { createContext, useContext } from 'react';

import type { ConversationGateway } from '@/features/conversations/gateway';

export const ConversationContext = createContext<ConversationGateway | null>(null);

export function useConversationGateway(): ConversationGateway {
  const ctx = useContext(ConversationContext);
  if (!ctx) throw new Error('useConversationGateway must be used within ConversationProvider');
  return ctx;
}
