import { lazy, Suspense, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Link, useLocation, useParams } from 'react-router';

import { useSession } from '@/features/authentication/sessionContext';
import { parseCitations } from '@/features/conversations/citationUtils';
import { useMessageSources, useMessages, useStreamMessage, useUpdateFocus } from '@/features/conversations/hooks';
import styles from '@/features/conversations/conversations.module.css';
import { useDocumentRegions, useDocumentUrl } from '@/features/documents/hooks';
import type { BoundingBox, Citation } from '@/schemas/conversation';
import type { DocumentRegion } from '@/schemas/document';
import type { MessageStatus } from '@/schemas/enums';

// The PDF viewer is large; split it into its own chunk so the main bundle stays lean.
const PdfViewer = lazy(() =>
  import('@/features/documents/PdfViewer').then((m) => ({ default: m.PdfViewer })),
);

const STATUS_FAILED: MessageStatus[] = ['FAILED', 'CANCELLED'];

/** Render assistant message text with inline citation chips replacing [S1]-style markers. */
function MessageWithCitations({
  content,
  citations,
  onCite,
}: {
  content: string;
  citations: Citation[];
  onCite?: (citation: Citation) => void;
}) {
  const citationByLabel = new Map(citations.map((c) => [c.label, c]));
  const parts = parseCitations(content);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 0 ? (
          <span key={i}>{part}</span>
        ) : (
          <sup
            key={i}
            className={styles.citationChip}
            data-label={part}
            aria-label={`Citation ${part}`}
            role="button"
            tabIndex={0}
            title={
              citationByLabel.has(part)
                ? `Page ${String(citationByLabel.get(part)!.page_number)}`
                : part
            }
            onClick={() => {
              const cit = citationByLabel.get(part);
              if (cit && onCite) onCite(cit);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                const cit = citationByLabel.get(part);
                if (cit && onCite) onCite(cit);
              }
            }}
          >
            [{part}]
          </sup>
        ),
      )}
    </>
  );
}

function SourcesPanel({
  kbId,
  convId,
  msgId,
  status,
}: {
  kbId: string;
  convId: string;
  msgId: string;
  status: MessageStatus;
}) {
  const { data: sources = [], isLoading } = useMessageSources(kbId, convId, msgId);
  if (isLoading) return <div className={styles.sourcesPanel}>Loading sources…</div>;
  const maxScore = sources.reduce((m, s) => Math.max(m, s.score), 0.001);
  return (
    <div className={styles.sourcesPanel}>
      {status === 'ABSTAINED' && (
        <p className={styles.sourcesAbstentionNote}>
          No passages with sufficient confidence — top candidates:
        </p>
      )}
      {sources.length === 0 ? (
        <p className={styles.sourcesEmpty}>No retrieval data recorded.</p>
      ) : (
        <ul className={styles.sourcesList}>
          {sources.map((s, i) => (
            <li key={`${s.document_id}-${i}`} className={styles.sourceRow}>
              <span className={styles.sourceName}>{s.document_name}</span>
              <span className={styles.sourcePage}>p.{s.page_number}</span>
              <div className={styles.sourceBarTrack} aria-hidden="true">
                <div
                  className={styles.sourceBar}
                  style={{ width: `${(s.score / maxScore) * 100}%` }}
                />
              </div>
              {s.cited && <span className={styles.sourceCited}>Cited</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ChatPage() {
  const { kbId, convId } = useParams<{ kbId: string; convId: string }>();
  const loc = useLocation();
  const locState = loc.state as {
    kbName?: string;
    convTitle?: string;
    activeDocumentId?: string | null;
  } | null;
  const kbName = locState?.kbName ?? 'Knowledge Base';
  const convTitle = locState?.convTitle ?? 'Conversation';
  const activeDocumentId = locState?.activeDocumentId ?? null;

  const { state, signOut } = useSession();
  const email = state.status === 'signed-in' ? state.session.email : null;

  const { data: messages, isLoading } = useMessages(kbId ?? '', convId ?? '');
  const { send, stop, tokens, isStreaming, streamError } = useStreamMessage(kbId ?? '', convId ?? '');
  const { mutateAsync: updateFocus } = useUpdateFocus(kbId ?? '', convId ?? '');

  // Which document is currently shown in the panel. Starts as the conversation's active document
  // (from router state) and updates whenever the student clicks a citation chip.
  const [panelDocumentId, setPanelDocumentId] = useState<string | null>(activeDocumentId);
  const [panelOpen, setPanelOpen] = useState(!!activeDocumentId);
  // The page and bounding box of the last-clicked citation chip.
  const [targetPage, setTargetPage] = useState<number | null>(null);
  const [activeBbox, setActiveBbox] = useState<BoundingBox | null>(null);
  // The table or figure the student has selected as context for the next question.
  const [activeRegion, setActiveRegion] = useState<{ id: string; type: 'table' | 'figure' } | null>(null);
  // Which assistant message's sources panel is open (null = all closed).
  const [sourcesOpenId, setSourcesOpenId] = useState<string | null>(null);

  const { data: docUrl } = useDocumentUrl(
    kbId ?? '',
    panelOpen ? panelDocumentId : null,
  );

  const { data: regions } = useDocumentRegions(
    kbId ?? '',
    panelOpen ? panelDocumentId : null,
  );

  const [query, setQuery] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const lastQueryRef = useRef<string>('');

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: 'smooth' });
  }, [messages, tokens]);

  function handleCite(cit: Citation) {
    setPanelDocumentId(cit.document_id);
    setPanelOpen(true);
    setTargetPage(cit.page_number);
    setActiveBbox(cit.bounding_box ?? null);
  }

  function handleClosePanel() {
    setPanelOpen(false);
    setTargetPage(null);
    setActiveBbox(null);
  }

  function handleRegionClick(region: DocumentRegion) {
    const focus =
      region.region_type === 'table'
        ? { active_table_id: region.id }
        : { active_figure_id: region.id };
    void updateFocus(focus);
    setActiveRegion({ id: region.id, type: region.region_type as 'table' | 'figure' });
  }

  function handleDeselect() {
    if (!activeRegion) return;
    const focus =
      activeRegion.type === 'table'
        ? { active_table_id: null }
        : { active_figure_id: null };
    void updateFocus(focus);
    setActiveRegion(null);
  }

  async function handleSend(e: FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || isStreaming) return;
    lastQueryRef.current = trimmed;
    setQuery('');
    await send(trimmed);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void handleSend(e as unknown as FormEvent);
    }
  }

  return (
    <div className={styles.chatLayout}>
      {/* ── Chat column ─────────────────────────────────────────────────── */}
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
          {activeDocumentId && !panelOpen ? (
            <button
              type="button"
              className={styles.pdfToggleBtn}
              onClick={() => {
                setPanelDocumentId(activeDocumentId);
                setPanelOpen(true);
                setTargetPage(null);
                setActiveBbox(null);
              }}
            >
              View PDF
            </button>
          ) : null}
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
                <div key={msg.id} className={styles.msgGroup}>
                  <div className={styles.failedMsg}>
                    {msg.content || 'This response could not be completed.'}
                  </div>
                  <button
                    type="button"
                    className={styles.sourcesToggle}
                    onClick={() => setSourcesOpenId((id) => (id === msg.id ? null : msg.id))}
                  >
                    Sources
                  </button>
                  {sourcesOpenId === msg.id && (
                    <SourcesPanel kbId={kbId ?? ''} convId={convId ?? ''} msgId={msg.id} status={msg.status} />
                  )}
                </div>
              );
            }
            if (msg.status === 'ABSTAINED') {
              return (
                <div key={msg.id} className={styles.msgGroup}>
                  <div className={styles.abstentionMsg} role="status">
                    The uploaded material does not contain enough information to answer this
                    question. Try asking something the documents cover, or upload more material.
                  </div>
                  <button
                    type="button"
                    className={styles.sourcesToggle}
                    onClick={() => setSourcesOpenId((id) => (id === msg.id ? null : msg.id))}
                  >
                    Sources
                  </button>
                  {sourcesOpenId === msg.id && (
                    <SourcesPanel kbId={kbId ?? ''} convId={convId ?? ''} msgId={msg.id} status={msg.status} />
                  )}
                </div>
              );
            }
            if (msg.status === 'CONFLICTING') {
              return (
                <div key={msg.id} className={styles.msgGroup}>
                  <div className={styles.conflictMsg} role="status">
                    Conflicting evidence was found in your material. The documents may
                    contradict each other on this topic. Review the sources before relying on
                    any answer here.
                  </div>
                  <button
                    type="button"
                    className={styles.sourcesToggle}
                    onClick={() => setSourcesOpenId((id) => (id === msg.id ? null : msg.id))}
                  >
                    Sources
                  </button>
                  {sourcesOpenId === msg.id && (
                    <SourcesPanel kbId={kbId ?? ''} convId={convId ?? ''} msgId={msg.id} status={msg.status} />
                  )}
                </div>
              );
            }
            return (
              <div key={msg.id} className={styles.msgGroup}>
                <div className={styles.assistantMsg}>
                  {msg.status === 'COMPLETED' ? (
                    <MessageWithCitations
                      content={msg.content}
                      citations={msg.citations ?? []}
                      onCite={handleCite}
                    />
                  ) : (
                    msg.content
                  )}
                </div>
                <button
                  type="button"
                  className={styles.sourcesToggle}
                  onClick={() => setSourcesOpenId((id) => (id === msg.id ? null : msg.id))}
                >
                  Sources
                </button>
                {sourcesOpenId === msg.id && (
                  <SourcesPanel kbId={kbId ?? ''} convId={convId ?? ''} msgId={msg.id} status={msg.status} />
                )}
              </div>
            );
          })}

          {isStreaming ? (
            <div className={styles.streamingMsg}>
              {tokens || ' '}
              <span className={styles.streamingCursor} aria-hidden="true" />
            </div>
          ) : null}

          {streamError ? (
            <div className={styles.streamError} role="alert">
              <span>{streamError}</span>
              <button
                type="button"
                className={styles.retryButton}
                onClick={() => void send(lastQueryRef.current)}
              >
                Retry
              </button>
            </div>
          ) : null}

          <div ref={bottomRef} className={styles.bottomAnchor} />
        </div>

        {activeRegion ? (
          <div className={styles.selectionChip}>
            <span>{activeRegion.type === 'table' ? 'Table' : 'Figure'} selected</span>
            <button
              type="button"
              className={styles.selectionChipDeselect}
              aria-label={`Deselect ${activeRegion.type}`}
              onClick={handleDeselect}
            >
              ✕
            </button>
          </div>
        ) : null}

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
          {isStreaming ? (
            <button className={styles.stopButton} type="button" onClick={stop}>
              Stop
            </button>
          ) : (
            <button className={styles.sendButton} type="submit" disabled={!query.trim()}>
              Send
            </button>
          )}
        </form>
      </div>

      {/* ── PDF panel ───────────────────────────────────────────────────── */}
      {panelOpen && panelDocumentId ? (
        <div className={styles.pdfPanel}>
          <div className={styles.pdfPanelHeader}>
            <span>Document</span>
            <button
              type="button"
              className={styles.pdfPanelClose}
              aria-label="Close PDF panel"
              onClick={handleClosePanel}
            >
              ✕
            </button>
          </div>
          {docUrl ? (
            <Suspense fallback={<div className={styles.loading}>Loading viewer…</div>}>
              <PdfViewer
                url={docUrl.url}
                targetPage={targetPage ?? undefined}
                overlay={activeBbox}
                regions={regions}
                onRegionClick={handleRegionClick}
              />
            </Suspense>
          ) : (
            <div className={styles.loading}>Fetching document…</div>
          )}
        </div>
      ) : null}
    </div>
  );
}
