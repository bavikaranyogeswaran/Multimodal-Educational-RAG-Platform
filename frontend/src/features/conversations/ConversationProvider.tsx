import { useMemo, type ReactNode } from 'react';

import { useApi } from '@/api/apiContext';
import { ApiConversationGateway } from '@/features/conversations/apiGateway';
import type { ConversationGateway } from '@/features/conversations/gateway';
import { ConversationContext } from '@/features/conversations/gatewayContext';

interface ConversationProviderProps {
  /** When supplied (e.g. in tests), skips building the API gateway. */
  gateway?: ConversationGateway | undefined;
  children: ReactNode;
}

export function ConversationProvider({ gateway, children }: ConversationProviderProps) {
  const client = useApi();
  const resolved = useMemo(
    () => gateway ?? new ApiConversationGateway(client),
    [gateway, client],
  );
  return <ConversationContext.Provider value={resolved}>{children}</ConversationContext.Provider>;
}
