import { z } from 'zod';

export const MemoryTypeSchema = z.enum([
  'PREFERENCE',
  'PROJECT_DECISION',
  'CONSTRAINT',
  'IDENTIFIER',
  'GOAL',
  'EXAM_DATE',
  'WEAK_TOPIC',
]);
export type MemoryType = z.infer<typeof MemoryTypeSchema>;

export const MemoryStatusSchema = z.enum([
  'ACTIVE',
  'SUPERSEDED',
  'DISPUTED',
  'UNCONFIRMED',
  'EXPIRED',
  'DELETED',
]);
export type MemoryStatus = z.infer<typeof MemoryStatusSchema>;

// Provenance is stored as an integer (IntEnum in Python)
export const MemoryProvenanceSchema = z.union([
  z.literal(10), // ASSISTANT_INFERENCE
  z.literal(20), // USER_STATEMENT
  z.literal(30), // APPLICATION_EVENT
  z.literal(40), // USER_CORRECTION
]);
export type MemoryProvenance = z.infer<typeof MemoryProvenanceSchema>;

export const MemoryFactSchema = z.object({
  id: z.string().uuid(),
  memory_type: MemoryTypeSchema,
  key: z.string(),
  value: z.record(z.unknown()),
  confidence: z.number().min(0).max(1),
  provenance: MemoryProvenanceSchema,
  status: MemoryStatusSchema,
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
  expires_at: z.string().datetime({ offset: true }).nullable(),
});
export type MemoryFact = z.infer<typeof MemoryFactSchema>;

export const MemoryFactListSchema = z.object({
  facts: z.array(MemoryFactSchema),
});
export type MemoryFactList = z.infer<typeof MemoryFactListSchema>;

export const MemoryUpdateRequestSchema = z.object({
  status: z.enum(['DISPUTED', 'DELETED']),
});
export type MemoryUpdateRequest = z.infer<typeof MemoryUpdateRequestSchema>;

export const PROVENANCE_LABELS: Record<MemoryProvenance, string> = {
  10: 'Inferred',
  20: 'Stated',
  30: 'App event',
  40: 'Correction',
};

export const TYPE_LABELS: Record<MemoryType, string> = {
  PREFERENCE: 'Preference',
  PROJECT_DECISION: 'Decision',
  CONSTRAINT: 'Constraint',
  IDENTIFIER: 'Identifier',
  GOAL: 'Goal',
  EXAM_DATE: 'Exam date',
  WEAK_TOPIC: 'Weak topic',
};
