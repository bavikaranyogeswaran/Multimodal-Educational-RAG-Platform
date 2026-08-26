import { useState, type FormEvent } from 'react';

import { useSession } from '@/features/authentication/sessionContext';
import {
  useCreateKnowledgeBase,
  useDeleteKnowledgeBase,
  useKnowledgeBases,
  useUpdateKnowledgeBase,
} from '@/features/knowledge-bases/hooks';
import styles from '@/features/knowledge-bases/knowledge-bases.module.css';
import type {
  CreateKnowledgeBaseRequest,
  KnowledgeBase,
  UpdateKnowledgeBaseRequest,
} from '@/schemas/knowledgeBase';

// ── Form ─────────────────────────────────────────────────────────────────

interface KnowledgeBaseFormProps {
  initial?: KnowledgeBase | undefined;
  pending: boolean;
  formError: string | null;
  onSave: (body: CreateKnowledgeBaseRequest) => Promise<void>;
  onCancel: () => void;
}

function KnowledgeBaseForm({
  initial,
  pending,
  formError,
  onSave,
  onCancel,
}: KnowledgeBaseFormProps) {
  const [name, setName] = useState(initial?.name ?? '');
  const [subject, setSubject] = useState(initial?.subject ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [level, setLevel] = useState<'INTRODUCTORY' | 'INTERMEDIATE' | 'ADVANCED'>(
    initial?.explanation_level ?? 'INTERMEDIATE',
  );

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await onSave({
      name,
      subject: subject.trim() || null,
      description: description.trim() || null,
      explanation_level: level,
    });
  }

  return (
    <form className={styles.form} onSubmit={(e) => void onSubmit(e)}>
      {formError ? (
        <p className={styles.error} role="alert">
          {formError}
        </p>
      ) : null}

      <div className={styles.field}>
        <label className={styles.label} htmlFor="kb-name">
          Name
        </label>
        <input
          className={styles.input}
          id="kb-name"
          required
          maxLength={200}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      <div className={styles.field}>
        <label className={styles.label} htmlFor="kb-subject">
          Subject
        </label>
        <input
          className={styles.input}
          id="kb-subject"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
        />
      </div>

      <div className={styles.field}>
        <label className={styles.label} htmlFor="kb-description">
          Description
        </label>
        <textarea
          className={styles.input}
          id="kb-description"
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>

      <div className={styles.field}>
        <label className={styles.label} htmlFor="kb-level">
          Explanation level
        </label>
        <select
          className={styles.input}
          id="kb-level"
          value={level}
          onChange={(e) => {
            const v = e.target.value;
            if (v === 'INTRODUCTORY' || v === 'INTERMEDIATE' || v === 'ADVANCED') setLevel(v);
          }}
        >
          <option value="INTRODUCTORY">Introductory</option>
          <option value="INTERMEDIATE">Intermediate</option>
          <option value="ADVANCED">Advanced</option>
        </select>
      </div>

      <div className={styles.formActions}>
        <button className={styles.saveButton} type="submit" disabled={pending}>
          {pending ? 'Saving…' : 'Save'}
        </button>
        <button className={styles.cancelButton} type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────

const LEVEL_LABELS: Record<string, string> = {
  INTRODUCTORY: 'Introductory',
  INTERMEDIATE: 'Intermediate',
  ADVANCED: 'Advanced',
};

export function KnowledgeBaseListPage() {
  const { state, signOut } = useSession();
  const email = state.status === 'signed-in' ? state.session.email : null;

  const { data: kbs, isLoading, isError } = useKnowledgeBases();
  const createMutation = useCreateKnowledgeBase();
  const updateMutation = useUpdateKnowledgeBase();
  const deleteMutation = useDeleteKnowledgeBase();

  const [editingKb, setEditingKb] = useState<KnowledgeBase | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  function openCreate() {
    setEditingKb(null);
    setFormError(null);
    setFormOpen(true);
  }

  function openEdit(kb: KnowledgeBase) {
    setEditingKb(kb);
    setFormError(null);
    setFormOpen(true);
  }

  function closeForm() {
    setFormOpen(false);
    setEditingKb(null);
    setFormError(null);
  }

  async function handleSave(body: CreateKnowledgeBaseRequest) {
    setFormError(null);
    try {
      if (editingKb) {
        const update: UpdateKnowledgeBaseRequest = body;
        await updateMutation.mutateAsync({ id: editingKb.id, body: update });
      } else {
        await createMutation.mutateAsync(body);
      }
      closeForm();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : 'Could not save.');
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteMutation.mutateAsync(id);
    } finally {
      setDeletingId(null);
    }
  }

  const formPending = createMutation.isPending || updateMutation.isPending;

  return (
    <>
      <header className={styles.nav}>
        <h1 className={styles.title}>Multimodal Educational Tutor</h1>
        <div className={styles.user}>
          {email ? <span className={styles.email}>{email}</span> : null}
          <button className={styles.signOut} type="button" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>

      <main className={styles.page}>
        <div className={styles.toolbar}>
          <h2 className={styles.pageTitle}>Knowledge Bases</h2>
          <button className={styles.newButton} type="button" onClick={openCreate}>
            New Knowledge Base
          </button>
        </div>

        {isLoading ? <p className={styles.loading}>Loading…</p> : null}

        {isError ? (
          <p className={styles.error} role="alert">
            Could not load your Knowledge Bases.
          </p>
        ) : null}

        {!isLoading && !isError && kbs?.length === 0 ? (
          <p className={styles.empty}>No Knowledge Bases yet. Create one to get started.</p>
        ) : null}

        {kbs && kbs.length > 0 ? (
          <ul className={styles.list}>
            {kbs.map((kb) => (
              <li key={kb.id} className={styles.card}>
                <div className={styles.cardTop}>
                  <strong className={styles.cardName}>{kb.name}</strong>
                  {kb.subject ? <span className={styles.cardSubject}>{kb.subject}</span> : null}
                </div>
                <div className={styles.cardMeta}>
                  <span className={styles.levelBadge}>
                    {LEVEL_LABELS[kb.explanation_level]}
                  </span>
                </div>
                <div className={styles.cardActions}>
                  <button
                    className={styles.editButton}
                    type="button"
                    onClick={() => openEdit(kb)}
                  >
                    Edit
                  </button>
                  {deletingId === kb.id ? (
                    <>
                      <button
                        className={styles.confirmButton}
                        type="button"
                        onClick={() => void handleDelete(kb.id)}
                      >
                        Confirm delete
                      </button>
                      <button
                        className={styles.cancelDeleteButton}
                        type="button"
                        onClick={() => setDeletingId(null)}
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      className={styles.deleteButton}
                      type="button"
                      onClick={() => setDeletingId(kb.id)}
                    >
                      Delete
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </main>

      {formOpen ? (
        <div className={styles.overlay}>
          <div className={styles.dialog} role="dialog" aria-modal="true">
            <h2 className={styles.dialogTitle}>
              {editingKb ? 'Edit Knowledge Base' : 'New Knowledge Base'}
            </h2>
            <KnowledgeBaseForm
              key={editingKb?.id ?? 'new'}
              initial={editingKb ?? undefined}
              pending={formPending}
              formError={formError}
              onSave={handleSave}
              onCancel={closeForm}
            />
          </div>
        </div>
      ) : null}
    </>
  );
}
