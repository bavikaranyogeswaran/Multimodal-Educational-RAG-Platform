import { Link } from 'react-router';

import styles from '@/pages/HomePage.module.css';

/**
 * An address that matches nothing.
 *
 * Deliberately says nothing about whether the thing exists but belongs to someone else.
 * The API answers those two cases identically for the same reason: a page that
 * distinguishes them turns the address bar into a way of testing for other people's
 * documents.
 */
export function NotFoundPage() {
  return (
    <main className={styles.shell}>
      <div className={styles.card}>
        <h1 className={styles.title}>Nothing here</h1>
        <p className={styles.body}>That address does not lead anywhere.</p>
        <Link to="/">Back to your Knowledge Bases</Link>
      </div>
    </main>
  );
}
