import type { ApiClient } from '@/api/client';
import {
  MemoryFactListSchema,
  MemoryFactSchema,
  type MemoryFact,
  type MemoryFactList,
} from '@/schemas/memory';

export class ApiMemoryGateway {
  readonly #client: ApiClient;

  constructor(client: ApiClient) {
    this.#client = client;
  }

  list = (kbId: string): Promise<MemoryFactList> =>
    this.#client.request(MemoryFactListSchema, `/knowledge-bases/${kbId}/memory`);

  dispute = (kbId: string, memoryId: string): Promise<MemoryFact> =>
    this.#client.request(
      MemoryFactSchema,
      `/knowledge-bases/${kbId}/memory/${memoryId}`,
      { method: 'PATCH', body: { status: 'DISPUTED' } },
    );

  remove = (kbId: string, memoryId: string): Promise<void> =>
    this.#client.requestNoContent(
      `/knowledge-bases/${kbId}/memory/${memoryId}`,
      { method: 'DELETE' },
    );
}
