import { useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation } from 'react-router';

import { useSession } from '@/features/authentication/sessionContext';
import styles from '@/features/authentication/authentication.module.css';

/**
 * Sign in.
 *
 * Somebody who is already signed in is sent on rather than shown this form again, which
 * also covers arriving here from a stale bookmark.
 */
export function SignInPage() {
  const { state, signIn } = useSession();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // Where the guard turned them away from, so signing in finishes that journey.
  const from = (location.state as { from?: string } | null)?.from ?? '/';

  if (state.status === 'signed-in') {
    return <Navigate to={from} replace />;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await signIn({ email, password });
    } catch (caught) {
      // The service's own wording is shown. Rewriting it here would mean guessing which
      // refusal it was, and the guesses that read best are the ones that mislead.
      setError(caught instanceof Error ? caught.message : 'Could not sign in.');
    } finally {
      setPending(false);
    }
  }

  return (
    <main className={styles.screen}>
      <div className={styles.card}>
        <h1 className={styles.title}>Sign in</h1>
        <p className={styles.subtitle}>Your study material, and answers grounded in it.</p>

        <form className={styles.form} onSubmit={(event) => void onSubmit(event)}>
          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}

          <div className={styles.field}>
            <label className={styles.label} htmlFor="email">
              Email
            </label>
            <input
              className={styles.input}
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor="password">
              Password
            </label>
            <input
              className={styles.input}
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>

          <button className={styles.submit} type="submit" disabled={pending}>
            {pending ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className={styles.switch}>
          No account yet? <Link to="/sign-up">Create one</Link>
        </p>
      </div>
    </main>
  );
}
