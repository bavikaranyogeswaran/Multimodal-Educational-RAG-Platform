import { useCallback, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useConversationGateway } from '@/features/conversations/gatewayContext';
import type { FocusUpdate } from '@/features/conversations/gateway';
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

export function useRenameConversation(kbId: string) {
  const gateway = useConversationGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ convId, title }: { convId: string; title: string }) =>
      gateway.rename(kbId, convId, title),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: convListKey(kbId) }),
  });
}

export function useRemoveConversation(kbId: string) {
  const gateway = useConversationGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (convId: string) => gateway.remove(kbId, convId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: convListKey(kbId) }),
  });
}

export function useUpdateFocus(kbId: string, convId: string) {
  const gateway = useConversationGateway();
  return useMutation({
    mutationFn: (focus: FocusUpdate) => gateway.updateFocus(kbId, convId, focus),
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
  // One controller per in-flight stream; null when idle.
  const controllerRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (query: string) => {
      const controller = new AbortController();
      controllerRef.current = controller;
      setIsStreaming(true);
      setTokens('');
      setStreamError(null);
      try {
        for await (const token of gateway.stream(kbId, convId, query, controller.signal)) {
          setTokens((prev) => prev + token);
        }
        // Stream ended cleanly — fetch the final recorded message.
        void queryClient.invalidateQueries({ queryKey: msgListKey(kbId, convId) });
      } catch (e) {
        if (e instanceof DOMException && e.name === 'AbortError') {
          // User stopped the stream deliberately — not an error. Still invalidate so the
          // CANCELLED message status is reflected without a manual refresh.
          void queryClient.invalidateQueries({ queryKey: msgListKey(kbId, convId) });
          return;
        }
        setStreamError(e instanceof Error ? e.message : 'Request failed.');
      } finally {
        setIsStreaming(false);
        setTokens('');
        controllerRef.current = null;
      }
    },
    [gateway, kbId, convId, queryClient],
  );

  const stop = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  return { send, stop, tokens, isStreaming, streamError };
}
