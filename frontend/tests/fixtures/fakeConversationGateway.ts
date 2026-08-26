import { vi } from 'vitest';

import type { ConversationGateway } from '@/features/conversations/gateway';
import {
  conversation as convSchema,
  message as msgSchema,
  type Conversation,
  type CreateConversationRequest,
  type Message,
} from '@/schemas/conversation';
import type { MessageRole, MessageStatus } from '@/schemas/enums';

export const aConversation = (
  overrides: Partial<{ title: string }> = {},
): Conversation =>
  convSchema.parse({
    id: crypto.randomUUID(),
    knowledge_base_id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
    title: overrides.title ?? 'Intro to Machine Learning',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T01:00:00Z',
    active_document_id: null,
    active_page_number: null,
    active_figure_id: null,
    active_table_id: null,
  });

export const aMessage = (
  overrides: Partial<{
    role: MessageRole;
    status: MessageStatus;
    content: string;
  }> = {},
): Message =>
  msgSchema.parse({
    id: crypto.randomUUID(),
    conversation_id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
    role: overrides.role ?? 'USER',
    status: overrides.status ?? 'COMPLETED',
    content: overrides.content ?? 'What is gradient descent?',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    rewritten_query: null,
    model_id: null,
    prompt_tokens: null,
    completion_tokens: null,
    finish_reason: null,
  });

export interface FakeConversationGateway extends ConversationGateway {
  convs: Conversation[];
  messages: Message[];
}

export function createFakeConversationGateway(
  initialConvs: Conversation[] = [],
  initialMessages: Message[] = [],
): FakeConversationGateway {
  const gateway: FakeConversationGateway = {
    convs: [...initialConvs],
    messages: [...initialMessages],

    list: vi.fn((_kbId: string): Promise<readonly Conversation[]> =>
      Promise.resolve(gateway.convs),
    ),

    create: vi.fn((_kbId: string, body: CreateConversationRequest): Promise<Conversation> => {
      const conv = aConversation({ title: body.title });
      gateway.convs = [...gateway.convs, conv];
      return Promise.resolve(conv);
    }),

    rename: vi.fn((_kbId: string, convId: string, title: string): Promise<Conversation> => {
      const existing = gateway.convs.find((c) => c.id === convId);
      const updated = existing
        ? { ...existing, title }
        : aConversation({ title });
      gateway.convs = gateway.convs.map((c) => (c.id === convId ? updated : c));
      return Promise.resolve(updated);
    }),

    remove: vi.fn((_kbId: string, convId: string): Promise<void> => {
      gateway.convs = gateway.convs.filter((c) => c.id !== convId);
      return Promise.resolve();
    }),

    listMessages: vi.fn(
      (_kbId: string, _convId: string): Promise<readonly Message[]> =>
        Promise.resolve(gateway.messages),
    ),

    stream: vi.fn(
      (_kbId: string, _convId: string, query: string): AsyncIterable<string> =>
        (async function* () {
          yield 'test ';
          yield 'response';
          // After yielding, update messages so the subsequent refetch returns the exchange.
          gateway.messages = [
            ...gateway.messages,
            aMessage({ role: 'USER', content: query }),
            aMessage({ role: 'ASSISTANT', content: 'test response' }),
          ];
        })(),
    ),
  };

  return gateway;
}
