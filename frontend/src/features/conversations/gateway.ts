import type {
  Conversation,
  CreateConversationRequest,
  Message,
} from '@/schemas/conversation';

export type FocusUpdate = {
  active_table_id?: string | null;
  active_figure_id?: string | null;
};

export interface ConversationGateway {
  list: (kbId: string) => Promise<readonly Conversation[]>;
  create: (kbId: string, body: CreateConversationRequest) => Promise<Conversation>;
  rename: (kbId: string, convId: string, title: string) => Promise<Conversation>;
  remove: (kbId: string, convId: string) => Promise<void>;
  updateFocus: (kbId: string, convId: string, focus: FocusUpdate) => Promise<Conversation>;
  listMessages: (kbId: string, convId: string) => Promise<readonly Message[]>;
  stream: (kbId: string, convId: string, query: string, signal?: AbortSignal) => AsyncIterable<string>;
}
