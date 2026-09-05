import { useState } from 'react';
import { Link, useLocation, useParams } from 'react-router';

import { useDeleteMemory, useDisputeMemory, useMemoryFacts } from '@/features/memory/hooks';
import styles from '@/features/memory/memory.module.css';
import {
  PROVENANCE_LABELS,
  TYPE_LABELS,
  type MemoryFact,
  type MemoryType,
} from '@/schemas/memory';

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatValue(value: Record<string, unknown>): string {
  const entries = Object.entries(value);
  if (entries.length === 0) return '—';
  if (entries.length === 1 && entries[0]) {
    const v = entries[0][1];
    return typeof v === 'string' ? v : JSON.stringify(v);
  }
  return entries.map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`).join('\n');
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function isExpiringSoon(expires_at: string | null): boolean {
  if (!expires_at) return false;
  const diff = new Date(expires_at).getTime() - Date.now();
  return diff > 0 && diff < 7 * 24 * 60 * 60 * 1000;
}

const TYPE_ORDER: MemoryType[] = [
  'GOAL',
  'EXAM_DATE',
  'PREFERENCE',
  'CONSTRAINT',
  'WEAK_TOPIC',
  'IDENTIFIER',
  'PROJECT_DECISION',
];

// ── Confirm delete dialog ─────────────────────────────────────────────────────

interface ConfirmDialogProps {
  fact: MemoryFact;
  onConfirm: () => void;
  onCancel: () => void;
}

function ConfirmDialog({ fact, onConfirm, onCancel }: ConfirmDialogProps) {
  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-labelledby="dlg-title">
      <div className={styles.dialog}>
        <p id="dlg-title" className={styles.dialogTitle}>Delete memory fact?</p>
        <p className={styles.dialogBody}>
          <strong>{fact.key}</strong> will be soft-deleted and will no longer influence your
          answers. This cannot be undone from the UI.
        </p>
        <div className={styles.dialogRow}>
          <button className={styles.btnCancel} onClick={onCancel}>Cancel</button>
          <button className={styles.btnConfirmDelete} onClick={onConfirm}>Delete</button>
        </div>
      </div>
    </div>
  );
}

// ── Fact card ─────────────────────────────────────────────────────────────────

interface FactCardProps {
  fact: MemoryFact;
  onDispute: () => void;
  onDelete: () => void;
  busy: boolean;
}

function FactCard({ fact, onDispute, onDelete, busy }: FactCardProps) {
  const confPct = Math.round(fact.confidence * 100);
  const expiring = isExpiringSoon(fact.expires_at);

  return (
    <div className={styles.card}>
      <div className={styles.cardMain}>
        <p className={styles.factKey}>{fact.key}</p>
        <p className={styles.factValue}>{formatValue(fact.value)}</p>
        <div className={styles.meta}>
          <span className={styles.badge}>{TYPE_LABELS[fact.memory_type]}</span>
          <span className={styles.provenance}>
            {PROVENANCE_LABELS[fact.provenance]}
          </span>
          <span className={styles.confidence}>
            {confPct}%
            <span className={styles.confBar} aria-hidden="true">
              <span
                className={styles.confFill}
                style={{ width: `${confPct}%` }}
              />
            </span>
          </span>
          {expiring && fact.expires_at && (
            <span className={styles.expiry}>
              Expires {formatDate(fact.expires_at)}
            </span>
          )}
          <span className={styles.date}>Added {formatDate(fact.created_at)}</span>
        </div>
      </div>
      <div className={styles.actions}>
        <button
          className={styles.btnDispute}
          disabled={busy}
          onClick={onDispute}
          title="Mark this fact as disputed — it will no longer influence answers"
        >
          Dispute
        </button>
        <button
          className={styles.btnDelete}
          disabled={busy}
          onClick={onDelete}
          title="Permanently remove this memory fact"
        >
          Delete
        </button>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function MemoryPage() {
  const { kbId } = useParams<{ kbId: string }>();
  const loc = useLocation();
  const kbName = (loc.state as { kbName?: string } | null)?.kbName ?? 'Knowledge Base';

  const { data, isLoading } = useMemoryFacts(kbId!);
  const disputeMut = useDisputeMemory(kbId!);
  const deleteMut = useDeleteMemory(kbId!);

  const [confirmId, setConfirmId] = useState<string | null>(null);

  const facts = data?.facts ?? [];
  const busy = disputeMut.isPending || deleteMut.isPending;

  // Group by type in a defined order
  const grouped = TYPE_ORDER.reduce<Record<MemoryType, MemoryFact[]>>(
    (acc, type) => {
      acc[type] = facts.filter((f) => f.memory_type === type);
      return acc;
    },
    {} as Record<MemoryType, MemoryFact[]>,
  );

  const confirmFact = facts.find((f) => f.id === confirmId) ?? null;

  return (
    <div className={styles.page}>
      {confirmFact && (
        <ConfirmDialog
          fact={confirmFact}
          onConfirm={() => {
            deleteMut.mutate(confirmFact.id);
            setConfirmId(null);
          }}
          onCancel={() => setConfirmId(null)}
        />
      )}

      <header className={styles.header}>
        <Link
          to={`/knowledge-bases/${kbId}`}
          state={{ kbName }}
          className={styles.backLink}
        >
          ← {kbName}
        </Link>
        <h1 className={styles.title}>Memory facts</h1>
        {facts.length > 0 && (
          <span className={styles.count}>{facts.length} active</span>
        )}
      </header>

      <div className={styles.body}>
        {isLoading && <p className={styles.emptyState}><span>Loading…</span></p>}

        {!isLoading && facts.length === 0 && (
          <div className={styles.emptyState}>
            <p>No memory facts yet.</p>
            <p>Facts are extracted during conversations and stored here.</p>
          </div>
        )}

        {!isLoading &&
          TYPE_ORDER.map((type) => {
            const group = grouped[type];
            if (!group || group.length === 0) return null;
            return (
              <section key={type}>
                <h2 className={styles.groupHeading}>{TYPE_LABELS[type]}</h2>
                {group.map((fact) => (
                  <FactCard
                    key={fact.id}
                    fact={fact}
                    busy={busy}
                    onDispute={() => disputeMut.mutate(fact.id)}
                    onDelete={() => setConfirmId(fact.id)}
                  />
                ))}
              </section>
            );
          })}
      </div>
    </div>
  );
}
