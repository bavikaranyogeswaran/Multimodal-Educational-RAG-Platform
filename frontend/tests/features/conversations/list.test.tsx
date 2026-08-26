import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it } from 'vitest';

import { SessionProvider } from '@/features/authentication/SessionProvider';
import { ConversationContext } from '@/features/conversations/gatewayContext';
import { ConversationListPage } from '@/features/conversations/ConversationListPage';
import { ChatPage } from '@/features/conversations/ChatPage';
import type { Conversation } from '@/schemas/conversation';
import { aSession, createFakeAuth } from '../../fixtures/fakeAuth';
import {
  aConversation,
  createFakeConversationGateway,
  type FakeConversationGateway,
} from '../../fixtures/fakeConversationGateway';

const KB_ID = 'kb-abc-123';

function renderPage(
  initialConvs: Conversation[] = [],
): { gateway: FakeConversationGateway } {
  const auth = createFakeAuth({ initial: aSession() });
  const gateway = createFakeConversationGateway(initialConvs);

  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <SessionProvider auth={auth}>
        <ConversationContext.Provider value={gateway}>
          <MemoryRouter initialEntries={[`/knowledge-bases/${KB_ID}/conversations`]}>
            <Routes>
              <Route
                path="/knowledge-bases/:kbId/conversations"
                element={<ConversationListPage />}
              />
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

describe('Conversation list', () => {
  it('shows the Conversations heading', async () => {
    renderPage();
    expect(await screen.findByRole('heading', { name: 'Conversations' })).toBeInTheDocument();
  });

  it('shows the empty state when there are no conversations', async () => {
    renderPage();
    expect(await screen.findByText(/No conversations yet/)).toBeInTheDocument();
  });

  it('shows each conversation by title', async () => {
    renderPage([
      aConversation({ title: 'What is gradient descent?' }),
      aConversation({ title: 'Explain backpropagation' }),
    ]);
    expect(await screen.findByText('What is gradient descent?')).toBeInTheDocument();
    expect(screen.getByText('Explain backpropagation')).toBeInTheDocument();
  });

  it('shows the create form when the button is clicked', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Conversations' });

    await userEvent.click(screen.getByRole('button', { name: 'New conversation' }));

    expect(screen.getByLabelText('Conversation title')).toBeInTheDocument();
  });

  it('creates a conversation and navigates to the chat page', async () => {
    const { gateway } = renderPage();
    await screen.findByRole('heading', { name: 'Conversations' });

    await userEvent.click(screen.getByRole('button', { name: 'New conversation' }));
    await userEvent.clear(screen.getByLabelText('Conversation title'));
    await userEvent.type(screen.getByLabelText('Conversation title'), 'Deep learning basics');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => {
      expect(gateway.create).toHaveBeenCalledWith(
        KB_ID,
        expect.objectContaining({ title: 'Deep learning basics' }),
      );
    });
    // After create, the chat page should load (ChatPage renders its input).
    expect(await screen.findByLabelText('Your question')).toBeInTheDocument();
  });

  it('renames a conversation and updates the title in the list', async () => {
    const conv = aConversation({ title: 'Original title' });
    const { gateway } = renderPage([conv]);
    await screen.findByText('Original title');

    await userEvent.click(screen.getByRole('button', { name: 'Rename' }));
    const input = screen.getByLabelText('Conversation title');
    await userEvent.clear(input);
    await userEvent.type(input, 'Updated title');
    await userEvent.keyboard('{Enter}');

    await waitFor(() => {
      expect(gateway.rename).toHaveBeenCalledWith(KB_ID, conv.id, 'Updated title');
    });
    expect(await screen.findByText('Updated title')).toBeInTheDocument();
  });

  it('cancels rename and leaves the title unchanged', async () => {
    const conv = aConversation({ title: 'Stable title' });
    renderPage([conv]);
    await screen.findByText('Stable title');

    await userEvent.click(screen.getByRole('button', { name: 'Rename' }));
    const input = screen.getByLabelText('Conversation title');
    await userEvent.clear(input);
    await userEvent.type(input, 'Abandoned edit');
    await userEvent.keyboard('{Escape}');

    // Rename form disappears and original title is still visible.
    expect(screen.queryByLabelText('Conversation title')).not.toBeInTheDocument();
    expect(screen.getByText('Stable title')).toBeInTheDocument();
  });

  it('deletes a conversation after confirming', async () => {
    const conv = aConversation({ title: 'Doomed conversation' });
    const { gateway } = renderPage([conv]);
    await screen.findByText('Doomed conversation');

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => {
      expect(gateway.remove).toHaveBeenCalledWith(KB_ID, conv.id);
    });
    await waitFor(() => {
      expect(screen.queryByText('Doomed conversation')).not.toBeInTheDocument();
    });
  });

  it('cancels delete and keeps the conversation in the list', async () => {
    const conv = aConversation({ title: 'Spared conversation' });
    renderPage([conv]);
    await screen.findByText('Spared conversation');

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    // Card is still present.
    expect(screen.getByText('Spared conversation')).toBeInTheDocument();
    // Delete button is back, confirm button is gone.
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm delete' })).not.toBeInTheDocument();
  });
});
