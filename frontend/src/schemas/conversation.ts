import { z } from 'zod';

import { messageRole, messageStatus } from '@/schemas/enums';
import { instant, uuid } from '@/schemas/primitives';

/**
 * Conversation and message responses.
 *
 * Mirrored now rather than when the chat screens are built. The contract is small, it is
 * read from the backend schema as it stands today, and a mirror written later is written
 * from whatever the API happens to return at that moment — which is the same thing only
 * as long as nobody changed it in between.
 */

export const conversation = z.object({
  id: uuid,
  knowledge_base_id: uuid,
  title: z.string(),
  created_at: instant,
  updated_at: instant,
  /** What the student is looking at, which narrows what a question is asked against. */
  active_document_id: uuid.nullable(),
  active_page_number: z.number().int().nullable(),
  active_figure_id: uuid.nullable(),
  active_table_id: uuid.nullable(),
});
export type Conversation = z.infer<typeof conversation>;

export const conversationList = z.array(conversation);

export const createConversationRequest = z.object({
  title: z.string().min(1).max(200),
  active_document_id: uuid.nullable().optional(),
  active_page_number: z.number().int().nullable().optional(),
  active_figure_id: uuid.nullable().optional(),
  active_table_id: uuid.nullable().optional(),
});
export type CreateConversationRequest = z.input<typeof createConversationRequest>;

export const streamRequest = z.object({
  query: z.string().min(1).max(4000),
});
export type StreamRequest = z.input<typeof streamRequest>;

/** The coordinates of one inline passage the model drew from. */
export const boundingBox = z.object({
  x0: z.number(),
  y0: z.number(),
  x1: z.number(),
  y1: z.number(),
});
export type BoundingBox = z.infer<typeof boundingBox>;

/** One source passage cited in an answer, identified by its label (e.g. "S1"). */
export const citation = z.object({
  label: z.string(),
  document_id: uuid,
  page_number: z.number().int(),
  chunk_type: z.string(),
  element_type: z.string().nullable().optional(),
  bounding_box: boundingBox.nullable().optional(),
  evidence_hash: z.string().nullable().optional(),
});
export type Citation = z.infer<typeof citation>;

export const message = z.object({
  id: uuid,
  conversation_id: uuid,
  role: messageRole,
  status: messageStatus,
  content: z.string(),
  created_at: instant,
  updated_at: instant,
  /** What retrieval actually searched for, which is not always what was typed. */
  rewritten_query: z.string().nullable(),
  model_id: z.string().nullable(),
  prompt_tokens: z.number().int().nullable(),
  completion_tokens: z.number().int().nullable(),
  finish_reason: z.string().nullable(),
  /** Source passages the model cited; empty when there are none. */
  citations: z.array(citation).optional().default([]),
});
export type Message = z.infer<typeof message>;

export const messageList = z.array(message);

/** One retrieved chunk shown in the sources panel after an answer renders. */
export const retrievalSource = z.object({
  document_id: uuid,
  document_name: z.string(),
  page_number: z.number().int(),
  score: z.number(),
  rank: z.number().int(),
  cited: z.boolean(),
});
export type RetrievalSource = z.infer<typeof retrievalSource>;
export const retrievalSourceList = z.array(retrievalSource);
