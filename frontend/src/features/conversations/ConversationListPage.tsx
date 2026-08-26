import { useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router';

import { useSession } from '@/features/authentication/sessionContext';
import {
  useConversations,
  useCreateConversation,
} from '@/features/conversations/hooks';
import styles from '@/features/conversations/conversations.module.css';

export function ConversationListPage() {
  const { kbId } = useParams<{ kbId: string }>();
  const loc = useLocation();
  const kbName = (loc.state as { kbName?: string } | null)?.kbName ?? 'Knowledge Base';
  const navigate = useNavigate();

  const { state, signOut } = useSession();
  const email = state.status === 'signed-in' ? state.session.email : null;

  const { data: convs, isLoading, isError } = useConversations(kbId ?? '');
  const createMutation = useCreateConversation(kbId ?? '');

  const [formOpen, setFormOpen] = useState(false);
  const [title, setTitle] = useState('');

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) return;
    const conv = await createMutation.mutateAsync({ title: trimmed });
    setFormOpen(false);
    setTitle('');
    void navigate(`/knowledge-bases/${kbId ?? ''}/conversations/${conv.id}`, {
      state: { kbName, convTitle: conv.title },
    });
  }

  function openCreate() {
    setTitle('New conversation');
    setFormOpen(true);
  }

  return (
    <div className={styles.chatShell}>
      <header className={styles.nav}>
        <h1 className={styles.title}>Multimodal Educational Tutor</h1>
        <div className={styles.user}>
          {email ? <span className={styles.email}>{email}</span> : null}
          <button className={styles.signOut} type="button" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>

      <div className={styles.breadcrumb}>
        <Link className={styles.back} to="/">← Knowledge Bases</Link>
        <span className={styles.breadSep}>›</span>
        <Link
          className={styles.back}
          to={`/knowledge-bases/${kbId ?? ''}`}
          state={{ kbName }}
        >
          Documents
        </Link>
        <span className={styles.breadSep}>›</span>
        <span className={styles.breadCurrent}>{kbName}</span>
      </div>

      <main className={styles.page}>
        <div className={styles.toolbar}>
          <h2 className={styles.pageTitle}>Conversations</h2>
          {!formOpen ? (
            <button className={styles.newButton} type="button" onClick={openCreate}>
              New conversation
            </button>
          ) : null}
        </div>

        {formOpen ? (
          <form className={styles.createForm} onSubmit={(e) => void handleCreate(e)}>
            <input
              className={styles.titleInput}
              aria-label="Conversation title"
              value={title}
              maxLength={200}
              required
              autoFocus
              onChange={(e) => setTitle(e.target.value)}
            />
            <button
              className={styles.createButton}
              type="submit"
              disabled={createMutation.isPending}
            >
              {createMutation.isPending ? 'Creating…' : 'Create'}
            </button>
            <button
              className={styles.cancelButton}
              type="button"
              onClick={() => setFormOpen(false)}
            >
              Cancel
            </button>
          </form>
        ) : null}

        {isLoading ? <p className={styles.loading}>Loading…</p> : null}
        {isError ? (
          <p className={styles.error} role="alert">
            Could not load conversations.
          </p>
        ) : null}

        {!isLoading && !isError && convs?.length === 0 ? (
          <p className={styles.empty}>No conversations yet. Start one to ask a question.</p>
        ) : null}

        {convs && convs.length > 0 ? (
          <ul className={styles.list}>
            {convs.map((conv) => (
              <li key={conv.id}>
                <Link
                  className={styles.convCard}
                  to={`/knowledge-bases/${kbId ?? ''}/conversations/${conv.id}`}
                  state={{ kbName, convTitle: conv.title }}
                >
                  <div className={styles.convTitle}>{conv.title}</div>
                  <div className={styles.convMeta}>
                    {new Date(conv.updated_at).toLocaleString()}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
      </main>
    </div>
  );
}
