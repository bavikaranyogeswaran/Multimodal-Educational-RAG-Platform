import type {
  CreateKnowledgeBaseRequest,
  KnowledgeBase,
  UpdateKnowledgeBaseRequest,
} from '@/schemas/knowledgeBase';

export interface KnowledgeBaseGateway {
  list: () => Promise<readonly KnowledgeBase[]>;
  create: (body: CreateKnowledgeBaseRequest) => Promise<KnowledgeBase>;
  update: (id: string, body: UpdateKnowledgeBaseRequest) => Promise<KnowledgeBase>;
  remove: (id: string) => Promise<void>;
}
