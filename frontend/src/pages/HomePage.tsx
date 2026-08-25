import { useSession } from '@/features/authentication/sessionContext';
import styles from '@/pages/HomePage.module.css';

/**
 * What a signed-in person lands on.
 *
 * A placeholder with one real job: showing that the session survived a reload and that
 * signing out works. The Knowledge Base list replaces its contents in the next step.
 */
export function HomePage() {
  const { state, signOut } = useSession();
  const email = state.status === 'signed-in' ? state.session.email : null;

  return (
    <main className={styles.shell}>
      <div className={styles.card}>
        <h1 className={styles.title}>Multimodal Educational Tutor</h1>
        <p className={styles.body}>
          Ask questions about your own study material and get answers grounded in it, with
          citations you can follow back to the page.
        </p>
        {email ? <p className={styles.identity}>{email}</p> : null}
        <div>
          <button className={styles.signOut} type="button" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </div>
    </main>
  );
}
