import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from '@/app/App';
import { AppProviders } from '@/app/AppProviders';
import { readEnv } from '@/app/env';
import {
  createSupabaseAuthGateway,
  createSupabaseClient,
} from '@/features/authentication/supabaseGateway';
import '@/app/global.css';

/**
 * Where the application is assembled.
 *
 * The one place that reads configuration and constructs the sign-in service. Everything
 * below is handed what it needs, which is what lets the whole tree be mounted in a test
 * against a stand-in without any of it knowing.
 */

const container = document.getElementById('root');

if (!container) {
  throw new Error('Root element #root is missing from index.html');
}

const root = createRoot(container);

try {
  const env = readEnv();
  const auth = createSupabaseAuthGateway(createSupabaseClient(env));

  root.render(
    <StrictMode>
      <AppProviders auth={auth} apiBaseUrl={env.apiBaseUrl}>
        <App />
      </AppProviders>
    </StrictMode>,
  );
} catch (caught) {
  // A misconfigured build otherwise renders an empty page, and the reason for it is a
  // console message nobody sees. Say what is wrong on the page itself.
  root.render(
    <pre
      style={{
        margin: '2rem',
        padding: '1rem',
        whiteSpace: 'pre-wrap',
        border: '1px solid currentColor',
        borderRadius: '0.5rem',
      }}
    >
      {caught instanceof Error ? caught.message : String(caught)}
    </pre>,
  );
}
