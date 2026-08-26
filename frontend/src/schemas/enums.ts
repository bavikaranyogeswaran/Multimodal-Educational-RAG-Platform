import { z } from 'zod';

/**
 * The enumerations the API sends, mirrored from the backend's own.
 *
 * Listed exhaustively rather than accepted as free strings. A value the backend adds and
 * this file does not know about should fail loudly here, at the one place that can be
 * corrected, instead of arriving in a component as a string that matches no branch and
 * renders as nothing at all.
 */

export const explanationLevel = z.enum(['INTRODUCTORY', 'INTERMEDIATE', 'ADVANCED']);
export type ExplanationLevel = z.infer<typeof explanationLevel>;

/** Where a document is in processing. DELETING is terminal from the reader's side. */
export const documentStatus = z.enum([
  'PENDING',
  'PROCESSING',
  'COMPLETED',
  'FAILED',
  'DELETING',
]);
export type DocumentStatus = z.infer<typeof documentStatus>;

export const messageRole = z.enum(['USER', 'ASSISTANT']);
export type MessageRole = z.infer<typeof messageRole>;

/**
 * A user message is stored before generation starts, so it carries a status of its own.
 * CANCELLED is separate from FAILED because nothing went wrong when a student stops
 * listening, and the two call for different things on screen.
 */
export const messageStatus = z.enum([
  'RECEIVED',
  'PROCESSING',
  'COMPLETED',
  'FAILED',
  'CANCELLED',
  // The model deliberately withheld the answer because the material does not cover the question.
  'ABSTAINED',
  // Contradictory evidence was found; the answer cannot be trusted until resolved.
  'CONFLICTING',
]);
export type MessageStatus = z.infer<typeof messageStatus>;
