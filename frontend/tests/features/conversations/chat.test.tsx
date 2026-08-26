import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it } from 'vitest';

import { SessionProvider } from '@/features/authentication/SessionProvider';
import { ConversationContext } from '@/features/conversations/gatewayContext';
import { ChatPage } from '@/features/conversations/ChatPage';
import type { Message } from '@/schemas/conversation';
import { aSession, createFakeAuth } from '../../fixtures/fakeAuth';
import {
  aMessage,
  createFakeConversationGateway,
  type FakeConversationGateway,
} from '../../fixtures/fakeConversationGateway';

const KB_ID = 'kb-abc-123';
const CONV_ID = 'conv-def-456';

function renderChat(
  initialMessages: Message[] = [],
  convTitle = 'Test conversation',
): { gateway: FakeConversationGateway } {
  const auth = createFakeAuth({ initial: aSession() });
  const gateway = createFakeConversationGateway([], initialMessages);

  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <SessionProvider auth={auth}>
        <ConversationContext.Provider value={gateway}>
          <MemoryRouter
            initialEntries={[
              {
                pathname: `/knowledge-bases/${KB_ID}/conversations/${CONV_ID}`,
                state: { kbName: 'Machine Learning', convTitle },
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
      </SessionProvider>
    </QueryClientProvider>,
  );

  return { gateway };
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
      expect(gateway.stream).toHaveBeenCalledWith(KB_ID, CONV_ID, 'Explain softmax');
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
    // The markers should be replaced by chip elements, not rendered as raw text.
    expect(await screen.findByRole('superscript', { name: /Citation S1/i })).toBeInTheDocument();
    expect(screen.getByRole('superscript', { name: /Citation S2/i })).toBeInTheDocument();
    // The surrounding plain text should still be present.
    expect(screen.getByText(/Gradient descent/)).toBeInTheDocument();
    expect(screen.getByText(/minimises loss/)).toBeInTheDocument();
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
});
