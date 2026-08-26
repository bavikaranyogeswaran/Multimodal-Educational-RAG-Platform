import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it } from 'vitest';

import { SessionProvider } from '@/features/authentication/SessionProvider';
import { DocumentContext } from '@/features/documents/gatewayContext';
import { DocumentListPage } from '@/features/documents/DocumentListPage';
import type { Document } from '@/schemas/document';
import { aSession, createFakeAuth } from '../../fixtures/fakeAuth';
import {
  aDocument,
  createFakeDocGateway,
  type FakeDocGateway,
} from '../../fixtures/fakeDocGateway';

const KB_ID = 'kb-abc-123';

function renderPage(initialDocs: Document[] = []): { gateway: FakeDocGateway } {
  const auth = createFakeAuth({ initial: aSession() });
  const gateway = createFakeDocGateway(initialDocs);

  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <SessionProvider auth={auth}>
        <DocumentContext.Provider value={gateway}>
          <MemoryRouter initialEntries={[`/knowledge-bases/${KB_ID}`]}>
            <Routes>
              <Route path="/knowledge-bases/:kbId" element={<DocumentListPage />} />
            </Routes>
          </MemoryRouter>
        </DocumentContext.Provider>
      </SessionProvider>
    </QueryClientProvider>,
  );

  return { gateway };
}

describe('Document list', () => {
  it('shows the Documents heading', async () => {
    renderPage();
    expect(await screen.findByRole('heading', { name: 'Documents' })).toBeInTheDocument();
  });

  it('shows the empty state when there are no documents', async () => {
    renderPage();
    expect(await screen.findByText(/No documents yet/)).toBeInTheDocument();
  });

  it('shows each document by filename', async () => {
    renderPage([aDocument({ filename: 'chapter-1.pdf' }), aDocument({ filename: 'chapter-2.pdf' })]);
    expect(await screen.findByText('chapter-1.pdf')).toBeInTheDocument();
    expect(screen.getByText('chapter-2.pdf')).toBeInTheDocument();
  });

  it('shows the status badge for a document', async () => {
    renderPage([aDocument({ status: 'COMPLETED' })]);
    expect(await screen.findByText('Ready')).toBeInTheDocument();
  });

  it('shows the failure reason for a failed document', async () => {
    renderPage([aDocument({ status: 'FAILED', failure_reason: 'Page limit exceeded' })]);
    expect(await screen.findByText('Page limit exceeded')).toBeInTheDocument();
  });

  it('rejects a non-PDF file before uploading', async () => {
    const { gateway } = renderPage();
    await screen.findByRole('heading', { name: 'Documents' });

    const file = new File(['content'], 'notes.txt', { type: 'text/plain' });
    // applyAccept: false bypasses the browser's accept-attribute filter so we can test
    // that our own validation rejects the file and shows an error.
    await userEvent.upload(screen.getByLabelText('Upload PDF'), file, { applyAccept: false });

    expect(await screen.findByRole('alert')).toHaveTextContent('Only PDF files');
    expect(gateway.upload).not.toHaveBeenCalled();
  });

  it('uploads a selected PDF', async () => {
    const { gateway } = renderPage();
    await screen.findByRole('heading', { name: 'Documents' });

    const file = new File(['%PDF-1.4'], 'lecture.pdf', { type: 'application/pdf' });
    await userEvent.upload(screen.getByLabelText('Upload PDF'), file);

    await waitFor(() => {
      expect(gateway.upload).toHaveBeenCalledWith(KB_ID, file);
    });
  });

  it('shows a confirm button when delete is clicked', async () => {
    renderPage([aDocument({ filename: 'to-delete.pdf' })]);
    await screen.findByText('to-delete.pdf');

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(screen.getByRole('button', { name: 'Confirm delete' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
  });

  it('restores the delete button when cancel is clicked', async () => {
    const { gateway } = renderPage([aDocument({ filename: 'to-delete.pdf' })]);
    await screen.findByText('to-delete.pdf');

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument();
    expect(gateway.remove).not.toHaveBeenCalled();
  });

  it('removes a document after confirming delete', async () => {
    const doc = aDocument({ filename: 'to-delete.pdf' });
    const { gateway } = renderPage([doc]);
    await screen.findByText('to-delete.pdf');

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => {
      expect(gateway.remove).toHaveBeenCalledWith(KB_ID, doc.id);
    });
  });
});
