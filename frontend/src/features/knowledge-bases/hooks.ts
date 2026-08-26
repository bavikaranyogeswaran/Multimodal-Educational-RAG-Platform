import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useKnowledgeBaseGateway } from '@/features/knowledge-bases/gatewayContext';
import type {
  CreateKnowledgeBaseRequest,
  UpdateKnowledgeBaseRequest,
} from '@/schemas/knowledgeBase';

const LIST_KEY = ['knowledge-bases'] as const;

export function useKnowledgeBases() {
  const gateway = useKnowledgeBaseGateway();
  return useQuery({
    queryKey: LIST_KEY,
    queryFn: () => gateway.list(),
  });
}

export function useCreateKnowledgeBase() {
  const gateway = useKnowledgeBaseGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateKnowledgeBaseRequest) => gateway.create(body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: LIST_KEY }),
  });
}

export function useUpdateKnowledgeBase() {
  const gateway = useKnowledgeBaseGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: UpdateKnowledgeBaseRequest }) =>
      gateway.update(id, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: LIST_KEY }),
  });
}

export function useDeleteKnowledgeBase() {
  const gateway = useKnowledgeBaseGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => gateway.remove(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: LIST_KEY }),
  });
}
