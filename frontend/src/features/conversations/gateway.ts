import type {
  Conversation,
  CreateConversationRequest,
  Message,
} from '@/schemas/conversation';

export interface ConversationGateway {
  list: (kbId: string) => Promise<readonly Conversation[]>;
  create: (kbId: string, body: CreateConversationRequest) => Promise<Conversation>;
  rename: (kbId: string, convId: string, title: string) => Promise<Conversation>;
  remove: (kbId: string, convId: string) => Promise<void>;
  listMessages: (kbId: string, convId: string) => Promise<readonly Message[]>;
  stream: (kbId: string, convId: string, query: string) => AsyncIterable<string>;
}
