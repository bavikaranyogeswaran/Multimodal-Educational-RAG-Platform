import type { Document, DocumentUpload } from '@/schemas/document';

export interface DocumentGateway {
  list: (kbId: string) => Promise<readonly Document[]>;
  upload: (kbId: string, file: File) => Promise<DocumentUpload>;
  remove: (kbId: string, documentId: string) => Promise<void>;
}
