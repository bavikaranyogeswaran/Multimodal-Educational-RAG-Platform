import { useState, type ChangeEvent } from 'react';
import { Link, useLocation, useParams } from 'react-router';

import { useSession } from '@/features/authentication/sessionContext';
import { useDeleteDocument, useDocuments, useUploadDocument } from '@/features/documents/hooks';
import styles from '@/features/documents/documents.module.css';
import type { Document } from '@/schemas/document';
import type { DocumentStatus } from '@/schemas/enums';

const STATUS_LABELS: Record<DocumentStatus, string> = {
  PENDING: 'Pending',
  PROCESSING: 'Processing…',
  COMPLETED: 'Ready',
  FAILED: 'Failed',
  DELETING: 'Deleting…',
};

function statusCls(status: DocumentStatus): string {
  if (status === 'COMPLETED') return styles.statusCompleted ?? '';
  if (status === 'FAILED') return styles.statusFailed ?? '';
  if (status === 'PROCESSING') return styles.statusProcessing ?? '';
  if (status === 'DELETING') return styles.statusDeleting ?? '';
  return styles.statusPending ?? '';
}

export function DocumentListPage() {
  const { kbId } = useParams<{ kbId: string }>();
  const loc = useLocation();
  const kbName = (loc.state as { kbName?: string } | null)?.kbName ?? 'Knowledge Base';

  const { state, signOut } = useSession();
  const email = state.status === 'signed-in' ? state.session.email : null;

  const { data: docs, isLoading, isError } = useDocuments(kbId ?? '');
  const uploadMutation = useUploadDocument(kbId ?? '');
  const deleteMutation = useDeleteDocument(kbId ?? '');

  const [fileError, setFileError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
    if (!isPdf) {
      setFileError('Only PDF files are accepted.');
      return;
    }
    setFileError(null);
    // Reset so the same file can be selected again after a successful upload.
    e.target.value = '';
    void uploadMutation.mutateAsync(file);
  }

  async function handleDelete(documentId: string) {
    try {
      await deleteMutation.mutateAsync(documentId);
    } finally {
      setDeletingId(null);
    }
  }

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
        <div className={styles.breadcrumb}>
          <Link className={styles.back} to="/">
            ← Knowledge Bases
          </Link>
          <span className={styles.kbName}>{kbName}</span>
        </div>

        <div className={styles.toolbar}>
          <h2 className={styles.pageTitle}>Documents</h2>
          <label className={styles.uploadLabel} htmlFor="doc-upload">
            {uploadMutation.isPending ? 'Uploading…' : 'Upload PDF'}
            <input
              className={styles.fileInput}
              id="doc-upload"
              type="file"
              accept=".pdf,application/pdf"
              disabled={uploadMutation.isPending}
              onChange={handleFileChange}
            />
          </label>
        </div>

        {fileError ? (
          <p className={styles.error} role="alert">
            {fileError}
          </p>
        ) : null}
        {uploadMutation.isError ? (
          <p className={styles.error} role="alert">
            {uploadMutation.error instanceof Error
              ? uploadMutation.error.message
              : 'Upload failed.'}
          </p>
        ) : null}

        {isLoading ? <p className={styles.loading}>Loading…</p> : null}
        {isError ? (
          <p className={styles.error} role="alert">
            Could not load documents.
          </p>
        ) : null}

        {!isLoading && !isError && docs?.length === 0 ? (
          <p className={styles.empty}>No documents yet. Upload a PDF to get started.</p>
        ) : null}

        {docs && docs.length > 0 ? (
          <ul className={styles.list}>
            {docs.map((doc: Document) => (
              <li key={doc.id} className={styles.card}>
                <div className={styles.cardTop}>
                  <strong className={styles.filename}>{doc.filename}</strong>
                  <span className={`${styles.statusBadge} ${statusCls(doc.status)}`}>
                    {STATUS_LABELS[doc.status]}
                  </span>
                </div>
                <div className={styles.cardMeta}>
                  {doc.page_count !== null ? (
                    <span>{doc.page_count} pages</span>
                  ) : null}
                  {doc.failure_reason ? (
                    <span className={styles.failureReason}>{doc.failure_reason}</span>
                  ) : null}
                </div>
                {doc.status !== 'DELETING' ? (
                  <div className={styles.cardActions}>
                    {deletingId === doc.id ? (
                      <>
                        <button
                          className={styles.confirmButton}
                          type="button"
                          onClick={() => void handleDelete(doc.id)}
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
                        onClick={() => setDeletingId(doc.id)}
                      >
                        Delete
                      </button>
                    )}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </main>
    </>
  );
}
