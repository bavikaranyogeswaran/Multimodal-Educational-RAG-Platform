import type { ApiClient } from '@/api/client';
import {
  GraphEntityDetailSchema,
  GraphResponseSchema,
  PrerequisiteViewSchema,
  RelatedViewSchema,
  type GraphEntityDetail,
  type GraphResponse,
  type PrerequisiteView,
  type RelatedView,
} from '@/schemas/graph';

export class ApiGraphGateway {
  readonly #client: ApiClient;

  constructor(client: ApiClient) {
    this.#client = client;
  }

  getGraph = (
    kbId: string,
    documentId: string,
    maxNodes = 50,
  ): Promise<GraphResponse> => {
    const params = new URLSearchParams({
      document_id: documentId,
      max_nodes: String(maxNodes),
    });
    return this.#client.request(
      GraphResponseSchema,
      `/knowledge-bases/${kbId}/graph?${params}`,
    );
  };

  getEntity = (kbId: string, entityId: string): Promise<GraphEntityDetail> =>
    this.#client.request(
      GraphEntityDetailSchema,
      `/knowledge-bases/${kbId}/graph/entities/${entityId}`,
    );

  getPrerequisites = (kbId: string, entityId: string): Promise<PrerequisiteView> =>
    this.#client.request(
      PrerequisiteViewSchema,
      `/knowledge-bases/${kbId}/graph/entities/${entityId}/prerequisites`,
    );

  getRelated = (kbId: string, entityId: string): Promise<RelatedView> =>
    this.#client.request(
      RelatedViewSchema,
      `/knowledge-bases/${kbId}/graph/entities/${entityId}/related`,
    );
}
