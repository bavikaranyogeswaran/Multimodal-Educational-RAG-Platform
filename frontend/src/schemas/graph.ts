import { z } from 'zod';

export const GraphNodeTypeSchema = z.enum([
  'KnowledgeBase',
  'Document',
  'Chapter',
  'Section',
  'Concept',
  'Figure',
  'Table',
]);
export type GraphNodeType = z.infer<typeof GraphNodeTypeSchema>;

export const RelationshipTypeSchema = z.enum([
  'CONTAINS',
  'PART_OF',
  'DEFINED_IN',
  'RELATED_TO',
  'PREREQUISITE_OF',
  'COMPARES_WITH',
  'EXPLAINED_BY',
  'SHOWN_IN',
  'REFERENCES',
]);
export type RelationshipType = z.infer<typeof RelationshipTypeSchema>;

export const GraphEntitySchema = z.object({
  id: z.string().uuid(),
  entity_type: GraphNodeTypeSchema,
  name: z.string(),
  description: z.string().nullable(),
  source_document_id: z.string().uuid().nullable(),
  page_number: z.number().int().nullable(),
});
export type GraphEntity = z.infer<typeof GraphEntitySchema>;

export const GraphRelationshipSchema = z.object({
  id: z.string().uuid(),
  source_entity_id: z.string().uuid(),
  target_entity_id: z.string().uuid(),
  relationship_type: RelationshipTypeSchema,
  page_number: z.number().int(),
  evidence: z.string(),
});
export type GraphRelationship = z.infer<typeof GraphRelationshipSchema>;

export const GraphResponseSchema = z.object({
  entities: z.array(GraphEntitySchema),
  relationships: z.array(GraphRelationshipSchema),
});
export type GraphResponse = z.infer<typeof GraphResponseSchema>;

export const GraphEntityDetailSchema = z.object({
  entity: GraphEntitySchema,
  relationships: z.array(GraphRelationshipSchema),
});
export type GraphEntityDetail = z.infer<typeof GraphEntityDetailSchema>;

export const PrerequisiteViewSchema = z.object({
  entity: GraphEntitySchema,
  prerequisites: z.array(GraphEntitySchema),
  unlocks: z.array(GraphEntitySchema),
  relationships: z.array(GraphRelationshipSchema),
});
export type PrerequisiteView = z.infer<typeof PrerequisiteViewSchema>;

export const RelatedViewSchema = z.object({
  entity: GraphEntitySchema,
  related: z.array(GraphEntitySchema),
  relationships: z.array(GraphRelationshipSchema),
});
export type RelatedView = z.infer<typeof RelatedViewSchema>;
