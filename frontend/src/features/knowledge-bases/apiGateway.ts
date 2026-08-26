import type { ApiClient } from '@/api/client';
import type { KnowledgeBaseGateway } from '@/features/knowledge-bases/gateway';
import {
  knowledgeBase,
  knowledgeBaseList,
  type CreateKnowledgeBaseRequest,
  type KnowledgeBase,
  type UpdateKnowledgeBaseRequest,
} from '@/schemas/knowledgeBase';

export class ApiKnowledgeBaseGateway implements KnowledgeBaseGateway {
  readonly #client: ApiClient;

  constructor(client: ApiClient) {
    this.#client = client;
  }

  list = (): Promise<readonly KnowledgeBase[]> =>
    this.#client.request(knowledgeBaseList, '/knowledge-bases');

  create = (body: CreateKnowledgeBaseRequest): Promise<KnowledgeBase> =>
    this.#client.request(knowledgeBase, '/knowledge-bases', { method: 'POST', body });

  update = (id: string, body: UpdateKnowledgeBaseRequest): Promise<KnowledgeBase> =>
    this.#client.request(knowledgeBase, `/knowledge-bases/${id}`, { method: 'PATCH', body });

  remove = (id: string): Promise<void> =>
    this.#client.requestNoContent(`/knowledge-bases/${id}`, { method: 'DELETE' });
}
