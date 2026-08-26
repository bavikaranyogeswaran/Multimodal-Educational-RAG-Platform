import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Link, useLocation, useParams } from 'react-router';

import { useSession } from '@/features/authentication/sessionContext';
import { parseCitations } from '@/features/conversations/citationUtils';
import { useMessages, useStreamMessage } from '@/features/conversations/hooks';
import styles from '@/features/conversations/conversations.module.css';
import type { Citation } from '@/schemas/conversation';
import type { MessageStatus } from '@/schemas/enums';

const STATUS_FAILED: MessageStatus[] = ['FAILED', 'CANCELLED'];

/** Render assistant message text with inline citation chips replacing [S1]-style markers. */
function MessageWithCitations({
  content,
  citations,
}: {
  content: string;
  citations: Citation[];
}) {
  // Build a label → citation index so each chip can be looked up by its label.
  const citationByLabel = new Map(citations.map((c) => [c.label, c]));
  const parts = parseCitations(content);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 0 ? (
          // Even indices are plain text segments — render as-is.
          <span key={i}>{part}</span>
        ) : (
          // Odd indices are citation labels captured from [S1] markers.
          // Clicking is a no-op for now; navigation to the source is added in a later step.
          <sup
            key={i}
            className={styles.citationChip}
            data-label={part}
            aria-label={`Citation ${part}`}
            title={
              citationByLabel.has(part)
                ? `Page ${String(citationByLabel.get(part)!.page_number)}`
                : part
            }
          >
            [{part}]
          </sup>
        ),
      )}
    </>
  );
}

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
          if (msg.status === 'ABSTAINED') {
            // The model had material but it did not address the question. This is a
            // deliberate outcome, so the banner frames it as a gap in the uploaded
            // documents rather than a system failure.
            return (
              <div key={msg.id} className={styles.abstentionMsg} role="status">
                The uploaded material does not contain enough information to answer this
                question. Try asking something the documents cover, or upload more material.
              </div>
            );
          }
          if (msg.status === 'CONFLICTING') {
            // Contradictory evidence was found. The answer exists but cannot be trusted
            // without resolving the conflict. Named explicitly so the student knows this
            // is about the content, not a technical failure.
            return (
              <div key={msg.id} className={styles.conflictMsg} role="status">
                Conflicting evidence was found in your material. The documents may
                contradict each other on this topic. Review the sources before relying on
                any answer here.
              </div>
            );
          }
          return (
            <div key={msg.id} className={styles.assistantMsg}>
              {msg.status === 'COMPLETED' ? (
                <MessageWithCitations content={msg.content} citations={msg.citations ?? []} />
              ) : (
                msg.content
              )}
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
