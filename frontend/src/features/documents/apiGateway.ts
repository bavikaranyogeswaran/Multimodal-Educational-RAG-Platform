import type { ApiClient } from '@/api/client';
import type { DocumentGateway } from '@/features/documents/gateway';
import {
  documentList,
  documentUpload,
  type Document,
  type DocumentUpload,
} from '@/schemas/document';

export class ApiDocumentGateway implements DocumentGateway {
  readonly #client: ApiClient;
  constructor(client: ApiClient) {
    this.#client = client;
  }

  list = (kbId: string): Promise<readonly Document[]> =>
    this.#client.request(documentList, `/knowledge-bases/${kbId}/documents`);

  upload = (kbId: string, file: File): Promise<DocumentUpload> => {
    const form = new FormData();
    form.append('file', file);
    return this.#client.request(documentUpload, `/knowledge-bases/${kbId}/documents`, {
      method: 'POST',
      body: form,
    });
  };

  remove = (kbId: string, documentId: string): Promise<void> =>
    this.#client.requestNoContent(`/knowledge-bases/${kbId}/documents/${documentId}`, {
      method: 'DELETE',
    });
}
