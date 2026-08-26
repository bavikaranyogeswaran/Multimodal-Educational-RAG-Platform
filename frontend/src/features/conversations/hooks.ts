import { useCallback, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useConversationGateway } from '@/features/conversations/gatewayContext';
import type { CreateConversationRequest } from '@/schemas/conversation';

const convListKey = (kbId: string) => ['conversations', kbId] as const;
const msgListKey = (kbId: string, convId: string) => ['messages', kbId, convId] as const;

export function useConversations(kbId: string) {
  const gateway = useConversationGateway();
  return useQuery({
    queryKey: convListKey(kbId),
    queryFn: () => gateway.list(kbId),
  });
}

export function useCreateConversation(kbId: string) {
  const gateway = useConversationGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateConversationRequest) => gateway.create(kbId, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: convListKey(kbId) }),
  });
}

export function useMessages(kbId: string, convId: string) {
  const gateway = useConversationGateway();
  return useQuery({
    queryKey: msgListKey(kbId, convId),
    queryFn: () => gateway.listMessages(kbId, convId),
  });
}

export function useStreamMessage(kbId: string, convId: string) {
  const gateway = useConversationGateway();
  const queryClient = useQueryClient();
  const [tokens, setTokens] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);

  const send = useCallback(
    async (query: string) => {
      setIsStreaming(true);
      setTokens('');
      setStreamError(null);
      try {
        for await (const token of gateway.stream(kbId, convId, query)) {
          setTokens((prev) => prev + token);
        }
        void queryClient.invalidateQueries({ queryKey: msgListKey(kbId, convId) });
      } catch (e) {
        setStreamError(e instanceof Error ? e.message : 'Request failed.');
      } finally {
        setIsStreaming(false);
        setTokens('');
      }
    },
    [gateway, kbId, convId, queryClient],
  );

  return { send, tokens, isStreaming, streamError };
}
