import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';

import { SessionProvider } from '@/features/authentication/SessionProvider';
import { KnowledgeBaseContext } from '@/features/knowledge-bases/gatewayContext';
import { KnowledgeBaseListPage } from '@/features/knowledge-bases/KnowledgeBaseListPage';
import { aSession, createFakeAuth } from '../../fixtures/fakeAuth';
import {
  aKnowledgeBase,
  createFakeKbGateway,
  type FakeKbGateway,
} from '../../fixtures/fakeKbGateway';
import type { KnowledgeBase } from '@/schemas/knowledgeBase';

function renderPage(initialKbs: KnowledgeBase[] = []): { gateway: FakeKbGateway } {
  const auth = createFakeAuth({ initial: aSession() });
  const gateway = createFakeKbGateway(initialKbs);

  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <SessionProvider auth={auth}>
        <KnowledgeBaseContext.Provider value={gateway}>
          <MemoryRouter>
            <KnowledgeBaseListPage />
          </MemoryRouter>
        </KnowledgeBaseContext.Provider>
      </SessionProvider>
    </QueryClientProvider>,
  );

  return { gateway };
}

describe('Knowledge Base list', () => {
  it('shows the page heading', async () => {
    renderPage();
    expect(await screen.findByRole('heading', { name: 'Knowledge Bases' })).toBeInTheDocument();
  });

  it('shows the empty state when there are no Knowledge Bases', async () => {
    renderPage();
    expect(await screen.findByText(/No Knowledge Bases yet/)).toBeInTheDocument();
  });

  it('shows each Knowledge Base by name', async () => {
    renderPage([
      aKnowledgeBase({ name: 'Calculus' }),
      aKnowledgeBase({ name: 'Thermodynamics' }),
    ]);
    expect(await screen.findByText('Calculus')).toBeInTheDocument();
    expect(screen.getByText('Thermodynamics')).toBeInTheDocument();
  });

  it('opens the create form when the button is clicked', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Knowledge Bases' });

    await userEvent.click(screen.getByRole('button', { name: 'New Knowledge Base' }));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'New Knowledge Base' })).toBeInTheDocument();
  });

  it('creates a Knowledge Base and closes the form', async () => {
    const { gateway } = renderPage();
    await screen.findByRole('heading', { name: 'Knowledge Bases' });

    await userEvent.click(screen.getByRole('button', { name: 'New Knowledge Base' }));
    await userEvent.clear(screen.getByLabelText('Name'));
    await userEvent.type(screen.getByLabelText('Name'), 'Organic Chemistry');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(gateway.create).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Organic Chemistry' }),
    );
  });

  it('opens the edit form pre-filled with the Knowledge Base data', async () => {
    renderPage([aKnowledgeBase({ name: 'Linear Algebra' })]);
    await screen.findByText('Linear Algebra');

    await userEvent.click(screen.getByRole('button', { name: 'Edit' }));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Edit Knowledge Base' })).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('Linear Algebra');
  });

  it('saves an edit and closes the form', async () => {
    const kb = aKnowledgeBase({ name: 'Old Name' });
    const { gateway } = renderPage([kb]);
    await screen.findByText('Old Name');

    await userEvent.click(screen.getByRole('button', { name: 'Edit' }));
    await userEvent.clear(screen.getByLabelText('Name'));
    await userEvent.type(screen.getByLabelText('Name'), 'New Name');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(gateway.update).toHaveBeenCalledWith(
      kb.id,
      expect.objectContaining({ name: 'New Name' }),
    );
  });

  it('shows a confirm button when delete is clicked', async () => {
    renderPage([aKnowledgeBase({ name: 'Genetics' })]);
    await screen.findByText('Genetics');

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(screen.getByRole('button', { name: 'Confirm delete' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
  });

  it('restores the delete button when cancel is clicked', async () => {
    const { gateway } = renderPage([aKnowledgeBase({ name: 'Genetics' })]);
    await screen.findByText('Genetics');

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument();
    expect(gateway.remove).not.toHaveBeenCalled();
  });

  it('removes a Knowledge Base after confirming delete', async () => {
    const kb = aKnowledgeBase({ name: 'Genetics' });
    const { gateway } = renderPage([kb]);
    await screen.findByText('Genetics');

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => {
      expect(gateway.remove).toHaveBeenCalledWith(kb.id);
    });
  });
});
