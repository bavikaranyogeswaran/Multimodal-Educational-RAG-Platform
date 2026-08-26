import { vi } from 'vitest';

import type { DocumentGateway } from '@/features/documents/gateway';
import {
  document as docSchema,
  documentUpload,
  type Document,
  type DocumentUpload,
  type DocumentUrl,
} from '@/schemas/document';
import type { DocumentStatus } from '@/schemas/enums';

export const aDocument = (
  overrides: Partial<{
    filename: string;
    status: DocumentStatus;
    page_count: number | null;
    failure_reason: string | null;
  }> = {},
): Document =>
  docSchema.parse({
    id: crypto.randomUUID(),
    knowledge_base_id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
    filename: overrides.filename ?? 'lecture-notes.pdf',
    content_type: 'application/pdf',
    byte_size: 102400,
    page_count: overrides.page_count ?? 10,
    status: overrides.status ?? 'COMPLETED',
    title: null,
    checksum: null,
    language: 'en',
    failure_reason: overrides.failure_reason ?? null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    processed_at: null,
  });

export const aDocumentUpload = (): DocumentUpload =>
  documentUpload.parse({
    document_id: crypto.randomUUID(),
    status: 'PENDING',
    page_count: 0,
  });

export interface FakeDocGateway extends DocumentGateway {
  docs: Document[];
}

export function createFakeDocGateway(initialDocs: Document[] = []): FakeDocGateway {
  const gateway: FakeDocGateway = {
    docs: [...initialDocs],

    list: vi.fn((_kbId: string): Promise<readonly Document[]> => Promise.resolve(gateway.docs)),

    upload: vi.fn((_kbId: string, _file: File): Promise<DocumentUpload> =>
      Promise.resolve(aDocumentUpload()),
    ),

    remove: vi.fn((_kbId: string, documentId: string): Promise<void> => {
      gateway.docs = gateway.docs.filter((d) => d.id !== documentId);
      return Promise.resolve();
    }),

    getDocumentUrl: vi.fn(
      (_kbId: string, _documentId: string): Promise<DocumentUrl> =>
        Promise.resolve({
          url: 'https://example.com/doc.pdf?sig=test',
          expires_at: new Date('2026-01-01T01:00:00Z'),
        }),
    ),
  };

  return gateway;
}
