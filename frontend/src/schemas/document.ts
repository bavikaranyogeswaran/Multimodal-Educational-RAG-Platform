import { z } from 'zod';

import { documentStatus } from '@/schemas/enums';
import { instant, uuid } from '@/schemas/primitives';

/** Document responses. Optional fields are nullable for the reason given alongside the
 * Knowledge Base schemas: the backend sends an explicit null rather than omitting a key. */

/** What an accepted upload reports back, before any of the file has been read. */
export const documentUpload = z.object({
  document_id: uuid,
  status: documentStatus,
  page_count: z.number().int(),
});
export type DocumentUpload = z.infer<typeof documentUpload>;

export const document = z.object({
  id: uuid,
  knowledge_base_id: uuid,
  filename: z.string(),
  content_type: z.string(),
  byte_size: z.number().int(),
  page_count: z.number().int().nullable(),
  status: documentStatus,
  title: z.string().nullable(),
  checksum: z.string().nullable(),
  language: z.string(),
  failure_reason: z.string().nullable(),
  created_at: instant,
  updated_at: instant,
  processed_at: instant.nullable(),
});
export type Document = z.infer<typeof document>;

export const documentList = z.array(document);

/**
 * The smaller shape the status endpoint returns, which is the one a screen polls while a
 * document is being read. It carries the failure reason because a poll that only reported
 * FAILED would leave the reader to guess, and guessing at someone else's file is unkind.
 */
export const documentStatusSnapshot = z.object({
  id: uuid,
  status: documentStatus,
  page_count: z.number().int().nullable(),
  failure_reason: z.string().nullable(),
  updated_at: instant,
});
export type DocumentStatusSnapshot = z.infer<typeof documentStatusSnapshot>;
