import { useState, type FormEvent, type KeyboardEvent } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router';

import { useSession } from '@/features/authentication/sessionContext';
import {
  useConversations,
  useCreateConversation,
  useRemoveConversation,
  useRenameConversation,
} from '@/features/conversations/hooks';
import styles from '@/features/conversations/conversations.module.css';
import type { Conversation } from '@/schemas/conversation';

const KB_ID_FALLBACK = '';

export function ConversationListPage() {
  const { kbId } = useParams<{ kbId: string }>();
  const loc = useLocation();
  const kbName = (loc.state as { kbName?: string } | null)?.kbName ?? 'Knowledge Base';
  const navigate = useNavigate();

  const { state, signOut } = useSession();
  const email = state.status === 'signed-in' ? state.session.email : null;

  const resolvedKbId = kbId ?? KB_ID_FALLBACK;
  const { data: convs, isLoading, isError } = useConversations(resolvedKbId);
  const createMutation = useCreateConversation(resolvedKbId);
  const renameMutation = useRenameConversation(resolvedKbId);
  const removeMutation = useRemoveConversation(resolvedKbId);

  const [formOpen, setFormOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameTitle, setRenameTitle] = useState('');
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) return;
    const conv = await createMutation.mutateAsync({ title: trimmed });
    setFormOpen(false);
    setTitle('');
    void navigate(`/knowledge-bases/${resolvedKbId}/conversations/${conv.id}`, {
      state: { kbName, convTitle: conv.title },
    });
  }

  function openCreate() {
    setTitle('New conversation');
    setFormOpen(true);
  }

  function startRename(conv: Conversation) {
    setRenamingId(conv.id);
    setRenameTitle(conv.title);
    setDeletingId(null);
  }

  function cancelRename() {
    setRenamingId(null);
    setRenameTitle('');
  }

  async function commitRename(convId: string) {
    const trimmed = renameTitle.trim();
    if (!trimmed) {
      cancelRename();
      return;
    }
    await renameMutation.mutateAsync({ convId, title: trimmed });
    cancelRename();
  }

  function handleRenameKeyDown(e: KeyboardEvent<HTMLInputElement>, convId: string) {
    if (e.key === 'Enter') {
      e.preventDefault();
      void commitRename(convId);
    }
    if (e.key === 'Escape') {
      cancelRename();
    }
  }

  async function handleDelete(convId: string) {
    try {
      await removeMutation.mutateAsync(convId);
    } finally {
      setDeletingId(null);
    }
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
          to={`/knowledge-bases/${resolvedKbId}`}
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
              <li key={conv.id} className={styles.convItem}>
                {renamingId === conv.id ? (
                  <div className={styles.convRenameRow}>
                    <input
                      className={styles.convRenameInput}
                      aria-label="Conversation title"
                      value={renameTitle}
                      maxLength={200}
                      autoFocus
                      onChange={(e) => setRenameTitle(e.target.value)}
                      onKeyDown={(e) => handleRenameKeyDown(e, conv.id)}
                      onBlur={() => void commitRename(conv.id)}
                    />
                    <button
                      className={styles.cardButton}
                      type="button"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={cancelRename}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <>
                    <Link
                      className={styles.convCardMain}
                      to={`/knowledge-bases/${resolvedKbId}/conversations/${conv.id}`}
                      state={{ kbName, convTitle: conv.title }}
                    >
                      <div className={styles.convTitle}>{conv.title}</div>
                      <div className={styles.convMeta}>
                        {new Date(conv.updated_at).toLocaleString()}
                      </div>
                    </Link>
                    <div className={styles.convActions}>
                      <button
                        className={styles.cardButton}
                        type="button"
                        onClick={() => startRename(conv)}
                      >
                        Rename
                      </button>
                      {deletingId === conv.id ? (
                        <>
                          <button
                            className={styles.cardDangerButton}
                            type="button"
                            onClick={() => void handleDelete(conv.id)}
                          >
                            Confirm delete
                          </button>
                          <button
                            className={styles.cardButton}
                            type="button"
                            onClick={() => setDeletingId(null)}
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <button
                          className={styles.cardDangerButton}
                          type="button"
                          onClick={() => setDeletingId(conv.id)}
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
        ) : null}
      </main>
    </div>
  );
}
