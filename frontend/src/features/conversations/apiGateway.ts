import type { ApiClient } from '@/api/client';
import type { ConversationGateway } from '@/features/conversations/gateway';
import {
  conversation,
  conversationList,
  messageList,
  type Conversation,
  type CreateConversationRequest,
  type Message,
} from '@/schemas/conversation';

export class ApiConversationGateway implements ConversationGateway {
  readonly #client: ApiClient;
  constructor(client: ApiClient) {
    this.#client = client;
  }

  list = (kbId: string): Promise<readonly Conversation[]> =>
    this.#client.request(conversationList, `/knowledge-bases/${kbId}/conversations`);

  create = (kbId: string, body: CreateConversationRequest): Promise<Conversation> =>
    this.#client.request(conversation, `/knowledge-bases/${kbId}/conversations`, {
      method: 'POST',
      body,
    });

  listMessages = (kbId: string, convId: string): Promise<readonly Message[]> =>
    this.#client.request(
      messageList,
      `/knowledge-bases/${kbId}/conversations/${convId}/messages`,
    );

  stream = (kbId: string, convId: string, query: string): AsyncIterable<string> =>
    this.#client.stream(
      `/knowledge-bases/${kbId}/conversations/${convId}/stream`,
      { body: { query } },
    );
}
