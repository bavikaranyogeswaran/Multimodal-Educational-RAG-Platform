import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';

import { App } from '@/app/App';
import { AppProviders } from '@/app/AppProviders';
import { aSession, createFakeAuth, type FakeAuth } from '../fixtures/fakeAuth';

/**
 * The whole tree, mounted the way the application mounts it.
 *
 * These go through `AppProviders` rather than rendering pages directly, because what is
 * being checked is the wiring: that the guard sits in front of the right routes and that
 * the providers nest in an order where each has what it depends on. A page rendered on
 * its own with hand-built context would pass while the real composition was broken.
 */

function mount(auth: FakeAuth, route = '/') {
  return render(
    <AppProviders
      auth={auth}
      apiBaseUrl=""
      router={(children: ReactNode) => (
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      )}
    >
      <App />
    </AppProviders>,
  );
}

describe('what a signed-out visitor sees', () => {
  it('is the sign-in screen, whatever they asked for', async () => {
    const auth = createFakeAuth({ initial: null });

    mount(auth, '/');

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('is the sign-up screen when they ask for it', async () => {
    const auth = createFakeAuth({ initial: null });

    mount(auth, '/sign-up');

    expect(
      await screen.findByRole('heading', { name: 'Create an account' }),
    ).toBeInTheDocument();
  });
});

describe('what a signed-in person sees', () => {
  it('is the application, with their address on it', async () => {
    const auth = createFakeAuth({ initial: aSession({ email: 'student@example.com' }) });

    mount(auth);

    expect(
      await screen.findByRole('heading', { name: 'Multimodal Educational Tutor' }),
    ).toBeInTheDocument();
    expect(screen.getByText('student@example.com')).toBeInTheDocument();
  });

  it('can sign out, and lands back on the sign-in screen', async () => {
    const auth = createFakeAuth({ initial: aSession() });
    mount(auth);
    await screen.findByRole('button', { name: 'Sign out' });

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    });
  });
});

describe('an address that matches nothing', () => {
  it('says so without revealing whether it belongs to somebody else', async () => {
    // The API answers not-found and not-yours identically, so that a URL cannot be used
    // to test for other people's documents. A page that distinguished them here would
    // undo that.
    const auth = createFakeAuth({ initial: aSession() });

    mount(auth, '/no/such/place');

    expect(await screen.findByRole('heading', { name: 'Nothing here' })).toBeInTheDocument();
  });
});

describe('styling', () => {
  it('scopes CSS Module class names rather than emitting them globally', async () => {
    const auth = createFakeAuth({ initial: aSession() });
    mount(auth);

    const heading = await screen.findByRole('heading', {
      name: 'Multimodal Educational Tutor',
    });
    // The scoping format differs between dev, test and production builds, so assert the
    // property that matters rather than the pattern: the local name is present, but the
    // emitted class is not the bare identifier that would leak into the global stylesheet.
    expect(heading.className).toContain('title');
    expect(heading.className).not.toBe('title');
  });
});
