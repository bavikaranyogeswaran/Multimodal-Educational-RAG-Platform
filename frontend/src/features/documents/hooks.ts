import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useDocumentGateway } from '@/features/documents/gatewayContext';

const listKey = (kbId: string) => ['documents', kbId] as const;

const POLLING_STATUSES = new Set(['PENDING', 'PROCESSING', 'DELETING']);

export function useDocuments(kbId: string) {
  const gateway = useDocumentGateway();
  return useQuery({
    queryKey: listKey(kbId),
    queryFn: () => gateway.list(kbId),
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.some((d) => POLLING_STATUSES.has(d.status)) ? 2000 : false;
    },
  });
}

export function useUploadDocument(kbId: string) {
  const gateway = useDocumentGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => gateway.upload(kbId, file),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: listKey(kbId) }),
  });
}

export function useDeleteDocument(kbId: string) {
  const gateway = useDocumentGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (documentId: string) => gateway.remove(kbId, documentId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: listKey(kbId) }),
  });
}
