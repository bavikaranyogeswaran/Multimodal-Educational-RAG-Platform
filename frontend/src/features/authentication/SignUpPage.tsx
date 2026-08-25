import { useState, type FormEvent } from 'react';
import { Link, Navigate } from 'react-router';

import { useSession } from '@/features/authentication/sessionContext';
import styles from '@/features/authentication/authentication.module.css';

/**
 * Create an account.
 *
 * Registering has two successful outcomes and they need different screens. Where the
 * project verifies email addresses, the account is created and no session comes back;
 * treating that as a completed sign-in would drop somebody into an application that
 * behaves as though they are signed out, with nothing on screen explaining why.
 */
export function SignUpPage() {
  const { state, signUp } = useSession();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [awaitingConfirmation, setAwaitingConfirmation] = useState(false);

  if (state.status === 'signed-in') {
    return <Navigate to="/" replace />;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      const outcome = await signUp({ email, password });
      if (outcome === 'confirmation-required') {
        setAwaitingConfirmation(true);
      }
      // The other outcome signs them in, and the redirect above carries them onward.
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not create the account.');
    } finally {
      setPending(false);
    }
  }

  return (
    <main className={styles.screen}>
      <div className={styles.card}>
        <h1 className={styles.title}>Create an account</h1>
        <p className={styles.subtitle}>Upload your own material and ask questions about it.</p>

        {awaitingConfirmation ? (
          <p className={styles.pending} role="status">
            Your account is created. Open the link we sent to {email} to finish setting it up,
            then sign in.
          </p>
        ) : (
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
                autoComplete="new-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>

            <button className={styles.submit} type="submit" disabled={pending}>
              {pending ? 'Creating…' : 'Create account'}
            </button>
          </form>
        )}

        <p className={styles.switch}>
          Already have an account? <Link to="/sign-in">Sign in</Link>
        </p>
      </div>
    </main>
  );
}
