import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Link, useLocation, useParams } from 'react-router';

import { useSession } from '@/features/authentication/sessionContext';
import { useMessages, useStreamMessage } from '@/features/conversations/hooks';
import styles from '@/features/conversations/conversations.module.css';
import type { MessageStatus } from '@/schemas/enums';

const STATUS_FAILED: MessageStatus[] = ['FAILED', 'CANCELLED'];

export function ChatPage() {
  const { kbId, convId } = useParams<{ kbId: string; convId: string }>();
  const loc = useLocation();
  const locState = loc.state as { kbName?: string; convTitle?: string } | null;
  const kbName = locState?.kbName ?? 'Knowledge Base';
  const convTitle = locState?.convTitle ?? 'Conversation';

  const { state, signOut } = useSession();
  const email = state.status === 'signed-in' ? state.session.email : null;

  const { data: messages, isLoading } = useMessages(kbId ?? '', convId ?? '');
  const { send, tokens, isStreaming, streamError } = useStreamMessage(kbId ?? '', convId ?? '');

  const [query, setQuery] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom whenever messages or streaming tokens change.
  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: 'smooth' });
  }, [messages, tokens]);

  async function handleSend(e: FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || isStreaming) return;
    setQuery('');
    await send(trimmed);
  }

  // Ctrl+Enter or Cmd+Enter submits the form.
  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void handleSend(e as unknown as FormEvent);
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
        <Link className={styles.back} to="/">
          ← Knowledge Bases
        </Link>
        <span className={styles.breadSep}>›</span>
        <Link
          className={styles.back}
          to={`/knowledge-bases/${kbId ?? ''}/conversations`}
          state={{ kbName }}
        >
          Conversations
        </Link>
        <span className={styles.breadSep}>›</span>
        <span className={styles.breadCurrent}>{convTitle}</span>
      </div>

      <div className={styles.messages}>
        {isLoading ? <p className={styles.loading}>Loading…</p> : null}

        {messages?.map((msg) => {
          if (msg.role === 'USER') {
            return (
              <div key={msg.id} className={styles.userMsg}>
                {msg.content}
              </div>
            );
          }
          if (STATUS_FAILED.includes(msg.status)) {
            return (
              <div key={msg.id} className={styles.failedMsg}>
                {msg.content || 'This response could not be completed.'}
              </div>
            );
          }
          return (
            <div key={msg.id} className={styles.assistantMsg}>
              {msg.content}
            </div>
          );
        })}

        {isStreaming ? (
          <div className={styles.streamingMsg}>
            {tokens || ' '}
            <span className={styles.streamingCursor} aria-hidden="true" />
          </div>
        ) : null}

        {streamError ? (
          <div className={styles.streamError} role="alert">
            {streamError}
          </div>
        ) : null}

        <div ref={bottomRef} className={styles.bottomAnchor} />
      </div>

      <form className={styles.inputRow} onSubmit={(e) => void handleSend(e)}>
        <textarea
          className={styles.queryInput}
          aria-label="Your question"
          placeholder="Ask a question… (Ctrl+Enter to send)"
          value={query}
          disabled={isStreaming}
          rows={1}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button className={styles.sendButton} type="submit" disabled={isStreaming || !query.trim()}>
          {isStreaming ? 'Answering…' : 'Send'}
        </button>
      </form>
    </div>
  );
}
