import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { App } from '@/app/App';
import { AppProviders } from '@/app/AppProviders';

describe('App', () => {
  it('renders the application shell', () => {
    render(<App />);

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Multimodal Educational Tutor',
    );
  });

  it('scopes CSS Module class names rather than emitting them globally', () => {
    render(<App />);

    const heading = screen.getByRole('heading', { level: 1 });
    // The scoping format differs between dev, test and production builds, so assert the
    // property that matters rather than the pattern: the local name is present, but the
    // emitted class is not the bare identifier that would leak into the global stylesheet.
    expect(heading.className).toContain('title');
    expect(heading.className).not.toBe('title');
  });

  it('mounts inside the application providers', () => {
    render(
      <AppProviders>
        <App />
      </AppProviders>,
    );

    expect(screen.getByRole('main')).toBeInTheDocument();
  });
});
