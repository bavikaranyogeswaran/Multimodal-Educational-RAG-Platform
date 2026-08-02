import styles from '@/app/App.module.css';

/**
 * Application shell.
 *
 * Routing, the authenticated layout and the Knowledge Base screens replace this later.
 * It exists now so the scaffold has something real to render and test.
 */
export function App() {
  return (
    <main className={styles.shell}>
      <div className={styles.card}>
        <h1 className={styles.title}>Multimodal Educational Tutor</h1>
        <p className={styles.body}>
          Ask questions about your own study material and get answers grounded in it, with
          citations you can follow back to the page.
        </p>
        <p className={styles.status}>foundation</p>
      </div>
    </main>
  );
}
