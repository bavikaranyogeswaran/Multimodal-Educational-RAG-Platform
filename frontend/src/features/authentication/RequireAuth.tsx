import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router';

import { useSession } from '@/features/authentication/sessionContext';
import styles from '@/features/authentication/authentication.module.css';

/**
 * Stands in front of everything that needs somebody signed in.
 *
 * The loading case renders rather than redirects, which is the whole reason the session
 * has three states. Redirecting while the stored session is still being read would send
 * a signed-in person to the sign-in screen on every reload, and — worse — lose the page
 * they had actually asked for.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { state } = useSession();
  const location = useLocation();

  if (state.status === 'loading') {
    return (
      <div className={styles.waiting} role="status" aria-live="polite">
        Checking your session…
      </div>
    );
  }

  if (state.status === 'signed-out') {
    // Where they were going is carried along, so signing in finishes the journey rather
    // than dropping them on a landing page to navigate again.
    return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}
