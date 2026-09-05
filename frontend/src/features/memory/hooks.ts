import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useApi } from '@/api/apiContext';
import { ApiMemoryGateway } from '@/features/memory/apiGateway';

const listKey = (kbId: string) => ['memory', kbId] as const;

function useGateway() {
  return new ApiMemoryGateway(useApi());
}

export function useMemoryFacts(kbId: string) {
  const gateway = useGateway();
  return useQuery({
    queryKey: listKey(kbId),
    queryFn: () => gateway.list(kbId),
  });
}

export function useDisputeMemory(kbId: string) {
  const gateway = useGateway();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (memoryId: string) => gateway.dispute(kbId, memoryId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: listKey(kbId) }),
  });
}

export function useDeleteMemory(kbId: string) {
  const gateway = useGateway();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (memoryId: string) => gateway.remove(kbId, memoryId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: listKey(kbId) }),
  });
}
