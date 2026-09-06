import type { ApiClient } from '@/api/client';
import {
  EpisodeListSchema,
  MemoryFactListSchema,
  MemoryFactSchema,
  type Episode,
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

  edit = (kbId: string, memoryId: string, newValue: string): Promise<MemoryFact> =>
    this.#client.request(
      MemoryFactSchema,
      `/knowledge-bases/${kbId}/memory/${memoryId}`,
      { method: 'PATCH', body: { new_value: newValue } },
    );

  listEpisodes = (kbId: string): Promise<Episode[]> =>
    this.#client.request(EpisodeListSchema, `/knowledge-bases/${kbId}/memory/episodes`);
}
