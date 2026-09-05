import { useQuery } from '@tanstack/react-query';

import { useApi } from '@/api/apiContext';
import { ApiGraphGateway } from '@/features/graph/apiGateway';

function useGateway() {
  const client = useApi();
  return new ApiGraphGateway(client);
}

export function useGraph(kbId: string, documentId: string | null) {
  const gateway = useGateway();
  return useQuery({
    queryKey: ['graph', kbId, documentId] as const,
    queryFn: () => gateway.getGraph(kbId, documentId!),
    enabled: !!documentId,
    staleTime: 5 * 60 * 1000,
  });
}

export function useGraphEntity(kbId: string, entityId: string | null) {
  const gateway = useGateway();
  return useQuery({
    queryKey: ['graph-entity', kbId, entityId] as const,
    queryFn: () => gateway.getEntity(kbId, entityId!),
    enabled: !!entityId,
    staleTime: 5 * 60 * 1000,
  });
}

export function useEntityPrerequisites(kbId: string, entityId: string | null) {
  const gateway = useGateway();
  return useQuery({
    queryKey: ['graph-prereqs', kbId, entityId] as const,
    queryFn: () => gateway.getPrerequisites(kbId, entityId!),
    enabled: !!entityId,
    staleTime: 5 * 60 * 1000,
  });
}

export function useEntityRelated(kbId: string, entityId: string | null) {
  const gateway = useGateway();
  return useQuery({
    queryKey: ['graph-related', kbId, entityId] as const,
    queryFn: () => gateway.getRelated(kbId, entityId!),
    enabled: !!entityId,
    staleTime: 5 * 60 * 1000,
  });
}
