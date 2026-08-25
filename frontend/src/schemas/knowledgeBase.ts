import { z } from 'zod';

import { explanationLevel } from '@/schemas/enums';
import { calendarDate, instant, uuid } from '@/schemas/primitives';

/**
 * Knowledge Base requests and responses.
 *
 * Every optional field is `.nullable()` and not `.optional()`, which is the shape the
 * backend actually sends: it serialises an unset field as an explicit null rather than
 * leaving the key out. Marking them optional would type them as possibly-absent and,
 * under this project's strict optional-property setting, force callers to handle an
 * `undefined` that never arrives while still leaving the null they will actually get.
 */

export const knowledgeBase = z.object({
  id: uuid,
  user_id: uuid,
  name: z.string(),
  description: z.string().nullable(),
  subject: z.string().nullable(),
  learning_goal: z.string().nullable(),
  preferred_language: z.string(),
  explanation_level: explanationLevel,
  exam_date: calendarDate.nullable(),
  graph_enabled: z.boolean(),
  active_index_version: z.number().int(),
  active_graph_version: z.number().int(),
  created_at: instant,
  updated_at: instant,
});
export type KnowledgeBase = z.infer<typeof knowledgeBase>;

export const knowledgeBaseList = z.array(knowledgeBase);

/**
 * What creating one accepts. The name bound is the backend's, repeated here so a name
 * that is going to be refused is refused before a request is spent finding that out.
 */
export const createKnowledgeBaseRequest = z.object({
  name: z.string().min(1).max(200),
  description: z.string().nullable().optional(),
  subject: z.string().nullable().optional(),
  learning_goal: z.string().nullable().optional(),
  preferred_language: z.string().nullable().optional(),
  explanation_level: explanationLevel.nullable().optional(),
  exam_date: calendarDate.nullable().optional(),
});
export type CreateKnowledgeBaseRequest = z.input<typeof createKnowledgeBaseRequest>;

/** Every field is optional on update, including the name, which may not be blanked. */
export const updateKnowledgeBaseRequest = createKnowledgeBaseRequest.partial();
export type UpdateKnowledgeBaseRequest = z.input<typeof updateKnowledgeBaseRequest>;

/**
 * What a queued rebuild reports.
 *
 * `active_index_version` is the version retrieval still answers from, and it stays that
 * way until every document has been read again — so a caller watching this number knows
 * the rebuild landed when it changes, rather than when the job was accepted.
 */
export const reindexResponse = z.object({
  knowledge_base_id: uuid,
  job_id: uuid,
  documents: z.number().int(),
  active_index_version: z.number().int(),
  target_index_version: z.number().int(),
});
export type ReindexResponse = z.infer<typeof reindexResponse>;
