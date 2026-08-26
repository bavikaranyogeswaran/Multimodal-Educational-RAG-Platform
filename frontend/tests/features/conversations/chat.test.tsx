import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it, vi } from 'vitest';

// Replace the lazy-loaded PDF viewer with a lightweight stub so chat tests
// don't pull in pdfjs-dist or its canvas requirements.
vi.mock('@/features/documents/PdfViewer', () => ({
  PdfViewer: ({
    url,
    targetPage,
    regions,
    onRegionClick,
  }: {
    url: string;
    targetPage?: number;
    regions?: readonly { id: string; region_type: string; page_number: number; bounding_box: { x0: number; y0: number; x1: number; y1: number } }[];
    onRegionClick?: (r: { id: string; region_type: string; page_number: number; bounding_box: { x0: number; y0: number; x1: number; y1: number } }) => void;
  }) => (
    <>
      <div data-testid="pdf-viewer" data-url={url} data-page={targetPage ?? ''} />
      {regions?.map((r) => (
        <button key={r.id} data-testid={`region-${r.id}`} onClick={() => onRegionClick?.(r)}>
          {r.region_type}
        </button>
      ))}
    </>
  ),
}));

import { SessionProvider } from '@/features/authentication/SessionProvider';
import { ConversationContext } from '@/features/conversations/gatewayContext';
import { ChatPage } from '@/features/conversations/ChatPage';
import { DocumentContext } from '@/features/documents/gatewayContext';
import type { Message } from '@/schemas/conversation';
import { aSession, createFakeAuth } from '../../fixtures/fakeAuth';
import {
  aMessage,
  createFakeConversationGateway,
  type FakeConversationGateway,
} from '../../fixtures/fakeConversationGateway';
import { createFakeDocGateway, type FakeDocGateway } from '../../fixtures/fakeDocGateway';

const KB_ID = 'kb-abc-123';
const CONV_ID = 'conv-def-456';

function renderChat(
  initialMessages: Message[] = [],
  convTitle = 'Test conversation',
  opts: { activeDocumentId?: string } = {},
): { gateway: FakeConversationGateway; docGateway: FakeDocGateway } {
  const auth = createFakeAuth({ initial: aSession() });
  const gateway = createFakeConversationGateway([], initialMessages);
  const docGateway = createFakeDocGateway();

  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <SessionProvider auth={auth}>
        <DocumentContext.Provider value={docGateway}>
          <ConversationContext.Provider value={gateway}>
            <MemoryRouter
              initialEntries={[
                {
                  pathname: `/knowledge-bases/${KB_ID}/conversations/${CONV_ID}`,
                  state: {
                    kbName: 'Machine Learning',
                    convTitle,
                    ...(opts.activeDocumentId ? { activeDocumentId: opts.activeDocumentId } : {}),
                  },
                },
              ]}
            >
              <Routes>
                <Route
                  path="/knowledge-bases/:kbId/conversations/:convId"
                  element={<ChatPage />}
                />
              </Routes>
            </MemoryRouter>
          </ConversationContext.Provider>
        </DocumentContext.Provider>
      </SessionProvider>
    </QueryClientProvider>,
  );

  return { gateway, docGateway };
}

describe('Chat page', () => {
  it('shows existing user messages', async () => {
    renderChat([aMessage({ role: 'USER', content: 'What is a neural network?' })]);
    expect(await screen.findByText('What is a neural network?')).toBeInTheDocument();
  });

  it('shows existing assistant messages', async () => {
    renderChat([
      aMessage({ role: 'ASSISTANT', status: 'COMPLETED', content: 'A neural network is…' }),
    ]);
    expect(await screen.findByText('A neural network is…')).toBeInTheDocument();
  });

  it('shows a failed assistant message differently', async () => {
    renderChat([
      aMessage({ role: 'ASSISTANT', status: 'FAILED', content: 'Could not verify answer.' }),
    ]);
    expect(await screen.findByText('Could not verify answer.')).toBeInTheDocument();
  });

  it('disables the send button when the input is empty', async () => {
    renderChat();
    await screen.findByRole('button', { name: 'Send' });
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
  });

  it('sends the query to the stream gateway', async () => {
    const { gateway } = renderChat();
    await screen.findByRole('button', { name: 'Send' });

    await userEvent.type(screen.getByLabelText('Your question'), 'Explain softmax');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => {
      expect(gateway.stream).toHaveBeenCalledWith(KB_ID, CONV_ID, 'Explain softmax', expect.any(AbortSignal));
    });
  });

  it('shows an abstention banner for ABSTAINED messages', async () => {
    renderChat([aMessage({ role: 'ASSISTANT', status: 'ABSTAINED', content: '' })]);
    expect(
      await screen.findByText(/does not contain enough information/i),
    ).toBeInTheDocument();
  });

  it('shows a conflict banner for CONFLICTING messages', async () => {
    renderChat([aMessage({ role: 'ASSISTANT', status: 'CONFLICTING', content: '' })]);
    expect(
      await screen.findByText(/conflicting evidence/i),
    ).toBeInTheDocument();
  });

  it('renders inline citation chips for COMPLETED assistant messages', async () => {
    renderChat([
      aMessage({
        role: 'ASSISTANT',
        status: 'COMPLETED',
        content: 'Gradient descent [S1] minimises loss [S2].',
        citations: [
          {
            label: 'S1',
            // Valid v4 UUID (version nibble = 4, variant nibble = 8).
            document_id: '00000000-0000-4000-8000-000000000001',
            page_number: 3,
            chunk_type: 'text',
          },
          {
            label: 'S2',
            document_id: '00000000-0000-4000-8000-000000000002',
            page_number: 7,
            chunk_type: 'text',
          },
        ],
      }),
    ]);
    // The markers should be replaced by chip buttons, not rendered as raw text.
    expect(await screen.findByRole('button', { name: /Citation S1/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Citation S2/i })).toBeInTheDocument();
    // The surrounding plain text should still be present.
    expect(screen.getByText(/Gradient descent/)).toBeInTheDocument();
    expect(screen.getByText(/minimises loss/)).toBeInTheDocument();
  });

  it('shows a Stop button while streaming and re-enables Send after stopping', async () => {
    // A stream that stalls indefinitely — aborts when the signal fires.
    const { gateway } = renderChat();
    gateway.stream = vi.fn(
      (_kbId: string, _convId: string, _query: string, signal?: AbortSignal) =>
        (async function* () {
          yield 'partial ';
          await new Promise<void>((_, reject) => {
            signal?.addEventListener('abort', () =>
              reject(new DOMException('Aborted', 'AbortError')),
            );
          });
        })(),
    );

    await userEvent.type(screen.getByLabelText('Your question'), 'test question');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    // Stop button appears while the stream is open.
    await screen.findByRole('button', { name: 'Stop' });

    // Clicking Stop should abort the stream and restore the Send button.
    await userEvent.click(screen.getByRole('button', { name: 'Stop' }));
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument();
    });
  });

  it('does not show a stream error when the stream is stopped deliberately', async () => {
    const { gateway } = renderChat();
    gateway.stream = vi.fn(
      (_kbId: string, _convId: string, _query: string, signal?: AbortSignal) =>
        (async function* () {
          await new Promise<void>((_, reject) => {
            signal?.addEventListener('abort', () =>
              reject(new DOMException('Aborted', 'AbortError')),
            );
          });
        })(),
    );

    await userEvent.type(screen.getByLabelText('Your question'), 'test question');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByRole('button', { name: 'Stop' });
    await userEvent.click(screen.getByRole('button', { name: 'Stop' }));

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument();
    });
    // No error, no Retry button.
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });

  it('shows a Retry button on stream failure and resends the original query', async () => {
    const { gateway } = renderChat();
    gateway.stream = vi.fn(
      () =>
        (async function* (): AsyncGenerator<string> {
          throw new Error('connection reset');
        })(),
    );

    await userEvent.type(screen.getByLabelText('Your question'), 'Explain backprop');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    // A Retry button appears after the failure.
    const retryBtn = await screen.findByRole('button', { name: 'Retry' });

    // Clicking Retry calls stream again with the same query that failed.
    await userEvent.click(retryBtn);
    await waitFor(() => {
      expect(gateway.stream).toHaveBeenCalledTimes(2);
      expect(gateway.stream).toHaveBeenLastCalledWith(
        KB_ID,
        CONV_ID,
        'Explain backprop',
        expect.any(AbortSignal),
      );
    });
  });

  it('shows the response in history after the stream completes', async () => {
    renderChat();
    await screen.findByRole('button', { name: 'Send' });

    await userEvent.type(screen.getByLabelText('Your question'), 'What is softmax?');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    // After the stream ends, the messages query is invalidated and refetched.
    // The fake gateway adds the assistant message to gateway.messages during
    // streaming, so the next listMessages call returns it.
    await waitFor(() => {
      expect(screen.getByText('test response')).toBeInTheDocument();
    });
  });

  it('clicking a citation chip opens the PDF viewer panel', async () => {
    renderChat([
      aMessage({
        role: 'ASSISTANT',
        status: 'COMPLETED',
        content: 'See gradient descent [S1] in the notes.',
        citations: [
          {
            label: 'S1',
            document_id: '00000000-0000-4000-8000-000000000001',
            page_number: 5,
            chunk_type: 'text',
          },
        ],
      }),
    ]);

    await userEvent.click(await screen.findByRole('button', { name: /Citation S1/i }));

    await waitFor(() => {
      expect(screen.getByTestId('pdf-viewer')).toBeInTheDocument();
    });
  });

  it('clicking a citation chip navigates the viewer to the cited page', async () => {
    renderChat([
      aMessage({
        role: 'ASSISTANT',
        status: 'COMPLETED',
        content: 'See [S1].',
        citations: [
          {
            label: 'S1',
            document_id: '00000000-0000-4000-8000-000000000001',
            page_number: 7,
            chunk_type: 'text',
          },
        ],
      }),
    ]);

    await userEvent.click(await screen.findByRole('button', { name: /Citation S1/i }));

    const viewer = await screen.findByTestId('pdf-viewer');
    expect(viewer).toHaveAttribute('data-page', '7');
  });

  it('clicking a table region calls updateFocus with the table id', async () => {
    const docId = '00000000-0000-4000-8000-000000000001';
    const tableId = '00000000-0000-4000-8000-000000000010';
    const { gateway, docGateway } = renderChat([
      aMessage({
        role: 'ASSISTANT',
        status: 'COMPLETED',
        content: 'See [S1].',
        citations: [{ label: 'S1', document_id: docId, page_number: 1, chunk_type: 'text' }],
      }),
    ]);

    docGateway.listRegions = vi.fn(() =>
      Promise.resolve([
        { id: tableId, region_type: 'table' as const, page_number: 1, bounding_box: { x0: 10, y0: 10, x1: 100, y1: 50 } },
      ]),
    );

    // Open the panel by clicking the citation chip.
    await userEvent.click(await screen.findByRole('button', { name: /Citation S1/i }));

    // Wait for the region button to appear (after listRegions resolves).
    await waitFor(() => expect(screen.getByTestId(`region-${tableId}`)).toBeInTheDocument());

    await userEvent.click(screen.getByTestId(`region-${tableId}`));

    await waitFor(() => {
      expect(gateway.updateFocus).toHaveBeenCalledWith(KB_ID, CONV_ID, { active_table_id: tableId });
    });
  });

  it('clicking a region shows a selection chip', async () => {
    const docId = '00000000-0000-4000-8000-000000000001';
    const tableId = '00000000-0000-4000-8000-000000000010';
    const { docGateway } = renderChat([
      aMessage({
        role: 'ASSISTANT',
        status: 'COMPLETED',
        content: 'See [S1].',
        citations: [{ label: 'S1', document_id: docId, page_number: 1, chunk_type: 'text' }],
      }),
    ]);

    docGateway.listRegions = vi.fn(() =>
      Promise.resolve([
        { id: tableId, region_type: 'table' as const, page_number: 1, bounding_box: { x0: 10, y0: 10, x1: 100, y1: 50 } },
      ]),
    );

    await userEvent.click(await screen.findByRole('button', { name: /Citation S1/i }));
    await waitFor(() => expect(screen.getByTestId(`region-${tableId}`)).toBeInTheDocument());
    await userEvent.click(screen.getByTestId(`region-${tableId}`));

    expect(await screen.findByText(/Table selected/i)).toBeInTheDocument();
  });

  it('clicking deselect clears the selection chip', async () => {
    const docId = '00000000-0000-4000-8000-000000000001';
    const tableId = '00000000-0000-4000-8000-000000000010';
    const { docGateway } = renderChat([
      aMessage({
        role: 'ASSISTANT',
        status: 'COMPLETED',
        content: 'See [S1].',
        citations: [{ label: 'S1', document_id: docId, page_number: 1, chunk_type: 'text' }],
      }),
    ]);

    docGateway.listRegions = vi.fn(() =>
      Promise.resolve([
        { id: tableId, region_type: 'table' as const, page_number: 1, bounding_box: { x0: 10, y0: 10, x1: 100, y1: 50 } },
      ]),
    );

    await userEvent.click(await screen.findByRole('button', { name: /Citation S1/i }));
    await waitFor(() => expect(screen.getByTestId(`region-${tableId}`)).toBeInTheDocument());
    await userEvent.click(screen.getByTestId(`region-${tableId}`));
    await screen.findByText(/Table selected/i);

    await userEvent.click(screen.getByRole('button', { name: /Deselect table/i }));

    await waitFor(() => {
      expect(screen.queryByText(/Table selected/i)).not.toBeInTheDocument();
    });
  });

  it('deselect sends a PATCH with null to clear the selection', async () => {
    const docId = '00000000-0000-4000-8000-000000000001';
    const tableId = '00000000-0000-4000-8000-000000000010';
    const { gateway, docGateway } = renderChat([
      aMessage({
        role: 'ASSISTANT',
        status: 'COMPLETED',
        content: 'See [S1].',
        citations: [{ label: 'S1', document_id: docId, page_number: 1, chunk_type: 'text' }],
      }),
    ]);

    docGateway.listRegions = vi.fn(() =>
      Promise.resolve([
        { id: tableId, region_type: 'table' as const, page_number: 1, bounding_box: { x0: 10, y0: 10, x1: 100, y1: 50 } },
      ]),
    );

    await userEvent.click(await screen.findByRole('button', { name: /Citation S1/i }));
    await waitFor(() => expect(screen.getByTestId(`region-${tableId}`)).toBeInTheDocument());
    await userEvent.click(screen.getByTestId(`region-${tableId}`));
    await screen.findByText(/Table selected/i);

    await userEvent.click(screen.getByRole('button', { name: /Deselect table/i }));

    await waitFor(() => {
      expect(gateway.updateFocus).toHaveBeenLastCalledWith(KB_ID, CONV_ID, { active_table_id: null });
    });
  });

  it('clicking a second chip updates the target page', async () => {
    renderChat([
      aMessage({
        role: 'ASSISTANT',
        status: 'COMPLETED',
        content: 'First [S1] then [S2].',
        citations: [
          {
            label: 'S1',
            document_id: '00000000-0000-4000-8000-000000000001',
            page_number: 3,
            chunk_type: 'text',
          },
          {
            label: 'S2',
            document_id: '00000000-0000-4000-8000-000000000001',
            page_number: 9,
            chunk_type: 'text',
          },
        ],
      }),
    ]);

    // Click the first chip — viewer opens at page 3.
    await userEvent.click(await screen.findByRole('button', { name: /Citation S1/i }));
    await waitFor(() =>
      expect(screen.getByTestId('pdf-viewer')).toHaveAttribute('data-page', '3'),
    );

    // Click the second chip — viewer updates to page 9.
    await userEvent.click(screen.getByRole('button', { name: /Citation S2/i }));
    await waitFor(() =>
      expect(screen.getByTestId('pdf-viewer')).toHaveAttribute('data-page', '9'),
    );
  });
});
