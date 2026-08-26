import type {
  Conversation,
  CreateConversationRequest,
  Message,
} from '@/schemas/conversation';

export interface ConversationGateway {
  list: (kbId: string) => Promise<readonly Conversation[]>;
  create: (kbId: string, body: CreateConversationRequest) => Promise<Conversation>;
  listMessages: (kbId: string, convId: string) => Promise<readonly Message[]>;
  stream: (kbId: string, convId: string, query: string) => AsyncIterable<string>;
}
