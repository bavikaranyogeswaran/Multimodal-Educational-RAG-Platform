import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it } from 'vitest';

import { SessionProvider } from '@/features/authentication/SessionProvider';
import { SignInPage } from '@/features/authentication/SignInPage';
import { SignUpPage } from '@/features/authentication/SignUpPage';
import { aSession, createFakeAuth, type FakeAuth } from '../../fixtures/fakeAuth';

/** The two screens somebody signed out can reach. */

function renderScreen(auth: FakeAuth, initialEntry: unknown = '/sign-in') {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <SessionProvider auth={auth}>
        <MemoryRouter initialEntries={[initialEntry as string]}>
          <Routes>
            <Route path="/sign-in" element={<SignInPage />} />
            <Route path="/sign-up" element={<SignUpPage />} />
            <Route path="/" element={<p>the application</p>} />
            <Route path="/documents" element={<p>the documents page</p>} />
          </Routes>
        </MemoryRouter>
      </SessionProvider>
    </QueryClientProvider>,
  );
}

describe('signing in', () => {
  it('passes what was typed to the sign-in service', async () => {
    const auth = createFakeAuth({ initial: null });
    renderScreen(auth);

    await userEvent.type(screen.getByLabelText('Email'), 'student@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'a-password');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => {
      expect(auth.signInCalls).toEqual([
        { email: 'student@example.com', password: 'a-password' },
      ]);
    });
  });

  it('shows the refusal in the service’s own words', async () => {
    // Rewriting it here would mean guessing which refusal it was, and the guesses that
    // read best are the ones that mislead: a wrong password and an unconfirmed address
    // call for different actions.
    const auth = createFakeAuth({ initial: null });
    auth.nextSignIn = { failure: 'Invalid login credentials' };
    renderScreen(auth);

    await userEvent.type(screen.getByLabelText('Email'), 'student@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid login credentials');
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled();
  });

  it('carries on to the page that was originally asked for', async () => {
    // The guard records where somebody was headed. Landing them on the home page instead
    // makes them navigate twice for one intention.
    const auth = createFakeAuth({ initial: null });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SessionProvider auth={auth}>
          <MemoryRouter
            initialEntries={[{ pathname: '/sign-in', state: { from: '/documents' } }]}
          >
            <Routes>
              <Route path="/sign-in" element={<SignInPage />} />
              <Route path="/documents" element={<p>the documents page</p>} />
              <Route path="/" element={<p>the application</p>} />
            </Routes>
          </MemoryRouter>
        </SessionProvider>
      </QueryClientProvider>,
    );

    await userEvent.type(screen.getByLabelText('Email'), 'student@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'a-password');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByText('the documents page')).toBeInTheDocument();
  });

  it('does not show the form to somebody already signed in', async () => {
    const auth = createFakeAuth({ initial: aSession() });
    renderScreen(auth);

    expect(await screen.findByText('the application')).toBeInTheDocument();
  });
});

describe('creating an account', () => {
  it('says what to do next when the address has to be confirmed', async () => {
    // The registration succeeded and produced no session. Treating that as a completed
    // sign-in drops somebody into an application that behaves as though they are signed
    // out, with nothing on screen explaining why.
    const auth = createFakeAuth({ initial: null });
    auth.nextSignUp = { outcome: 'confirmation-required' };
    renderScreen(auth, '/sign-up');

    await userEvent.type(screen.getByLabelText('Email'), 'student@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'a-password');
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }));

    const notice = await screen.findByRole('status');
    expect(notice).toHaveTextContent('student@example.com');
    expect(screen.queryByText('the application')).not.toBeInTheDocument();
  });

  it('shows the refusal when the service rejects the registration', async () => {
    const auth = createFakeAuth({ initial: null });
    auth.nextSignUp = { failure: 'Password should be at least 6 characters' };
    renderScreen(auth, '/sign-up');

    await userEvent.type(screen.getByLabelText('Email'), 'student@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'short');
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('at least 6 characters');
  });
});
