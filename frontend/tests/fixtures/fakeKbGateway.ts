import { vi } from 'vitest';

import type { KnowledgeBaseGateway } from '@/features/knowledge-bases/gateway';
import {
  knowledgeBase,
  type CreateKnowledgeBaseRequest,
  type KnowledgeBase,
  type UpdateKnowledgeBaseRequest,
} from '@/schemas/knowledgeBase';

export const aKnowledgeBase = (
  overrides: Partial<{ name: string; subject: string | null; description: string | null }> = {},
): KnowledgeBase =>
  knowledgeBase.parse({
    id: crypto.randomUUID(),
    user_id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
    name: overrides.name ?? 'Machine Learning',
    description: overrides.description ?? null,
    subject: overrides.subject ?? null,
    learning_goal: null,
    preferred_language: 'en',
    explanation_level: 'INTERMEDIATE',
    exam_date: null,
    graph_enabled: false,
    active_index_version: 1,
    active_graph_version: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  });

export interface FakeKbGateway extends KnowledgeBaseGateway {
  kbs: KnowledgeBase[];
}

export function createFakeKbGateway(initialKbs: KnowledgeBase[] = []): FakeKbGateway {
  const gateway: FakeKbGateway = {
    kbs: [...initialKbs],

    list: vi.fn((): Promise<readonly KnowledgeBase[]> => Promise.resolve(gateway.kbs)),

    create: vi.fn((body: CreateKnowledgeBaseRequest): Promise<KnowledgeBase> => {
      const kb = aKnowledgeBase({ name: body.name, subject: body.subject ?? null });
      gateway.kbs = [...gateway.kbs, kb];
      return Promise.resolve(kb);
    }),

    update: vi.fn((id: string, body: UpdateKnowledgeBaseRequest): Promise<KnowledgeBase> => {
      const existing = gateway.kbs.find((k) => k.id === id);
      if (!existing) return Promise.reject(new Error(`Knowledge Base not found: ${id}`));
      const changes = Object.fromEntries(
        Object.entries(body).filter(([, v]) => v !== undefined),
      ) as Partial<KnowledgeBase>;
      const updated = { ...existing, ...changes };
      gateway.kbs = gateway.kbs.map((k) => (k.id === id ? updated : k));
      return Promise.resolve(updated);
    }),

    remove: vi.fn((id: string): Promise<void> => {
      gateway.kbs = gateway.kbs.filter((k) => k.id !== id);
      return Promise.resolve();
    }),
  };

  return gateway;
}
