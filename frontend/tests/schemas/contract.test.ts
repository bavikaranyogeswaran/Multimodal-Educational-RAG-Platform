import { describe, expect, it } from 'vitest';

import { conversation, message } from '@/schemas/conversation';
import { document, documentStatusSnapshot, documentUpload } from '@/schemas/document';
import { errorBody } from '@/schemas/errors';
import { knowledgeBase, reindexResponse } from '@/schemas/knowledgeBase';
import {
  assistantMessage,
  conversationNew,
  documentSparse,
  documentStatusSnapshotProcessing,
  documentUploaded,
  domainError,
  knowledgeBaseFull,
  knowledgeBaseSparse,
  reindexAccepted,
  validationError,
} from '../fixtures/backendResponses';

/**
 * The contract mirror, checked against real backend output.
 *
 * These are worth more than their size suggests. Every screen built after this one reads
 * the API through these schemas, so a mismatch here does not produce a wrong value in one
 * place — it produces a parse failure everywhere the field appears, and the fixtures are
 * the only thing standing between a rename on the server and finding out from a user.
 */

describe('responses the backend actually sends', () => {
  it.each([
    ['a fully populated Knowledge Base', knowledgeBase, knowledgeBaseFull],
    ['a Knowledge Base with every optional unset', knowledgeBase, knowledgeBaseSparse],
    ['a queued rebuild', reindexResponse, reindexAccepted],
    ['an accepted upload', documentUpload, documentUploaded],
    ['a document with every optional unset', document, documentSparse],
    ['a processing snapshot', documentStatusSnapshot, documentStatusSnapshotProcessing],
    ['a new conversation', conversation, conversationNew],
    ['an assistant message', message, assistantMessage],
  ])('parses %s', (_label, schema, fixture) => {
    const result = schema.safeParse(fixture);

    expect(result.success, JSON.stringify(result.error?.issues)).toBe(true);
  });
});

describe('the null-versus-absent distinction', () => {
  it('accepts an explicit null for an optional field, which is what arrives', () => {
    // The backend serialises every field, so an unset description is present and null
    // rather than missing. A schema marking it optional would type it as possibly
    // undefined — a case that never happens — while still having to handle the null.
    const parsed = knowledgeBase.parse(knowledgeBaseSparse);

    expect(parsed.description).toBeNull();
    expect(parsed.exam_date).toBeNull();
    expect('description' in parsed).toBe(true);
  });

  it('refuses a required field that is missing rather than defaulting it', () => {
    const { name, ...withoutName } = knowledgeBaseFull;
    void name;

    expect(knowledgeBase.safeParse(withoutName).success).toBe(false);
  });
});

describe('time', () => {
  it('parses a timestamp into the instant it names', () => {
    const parsed = knowledgeBase.parse(knowledgeBaseFull);

    expect(parsed.created_at).toBeInstanceOf(Date);
    expect(parsed.created_at.toISOString()).toBe('2026-08-25T19:38:49.123Z');
  });

  it('accepts an offset as well as a trailing Z', () => {
    // Everything stored is UTC today. A value carrying a real offset is still a correct
    // instant, and refusing it would turn a change of timezone into a parse failure.
    const parsed = knowledgeBase.parse({
      ...knowledgeBaseFull,
      created_at: '2026-08-25T21:38:49.123456+02:00',
    });

    expect(parsed.created_at.toISOString()).toBe('2026-08-25T19:38:49.123Z');
  });

  it('leaves a calendar date as its three parts', () => {
    // The trap this avoids: passing it through Date fixes it to midnight UTC, so an exam
    // set for the first of December reads as the thirtieth of November west of Greenwich.
    const parsed = knowledgeBase.parse(knowledgeBaseFull);

    expect(parsed.exam_date).toBe('2026-12-01');
  });
});

describe('enumerations', () => {
  it('refuses a value the backend has not declared', () => {
    // The failure mode this prevents is silent: an unknown level reaching a component
    // matches no branch and renders as nothing, with no error anywhere to explain it.
    const result = knowledgeBase.safeParse({
      ...knowledgeBaseFull,
      explanation_level: 'EXPERT',
    });

    expect(result.success).toBe(false);
  });

  it('accepts every status a document can hold', () => {
    for (const status of ['PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', 'DELETING']) {
      expect(document.safeParse({ ...documentSparse, status }).success).toBe(true);
    }
  });

  it('accepts a cancelled message, which is not a failed one', () => {
    const parsed = message.parse({ ...assistantMessage, status: 'CANCELLED' });

    expect(parsed.status).toBe('CANCELLED');
  });
});

describe('the two error shapes', () => {
  it('parses the one the application raises', () => {
    const parsed = errorBody.parse(domainError);

    expect(parsed.detail).toBe('Widget not found');
  });

  it('parses the one the framework raises, which carries no trace id', () => {
    // Both arrive as 422, so the status cannot tell them apart and the client has to.
    const parsed = errorBody.parse(validationError);

    expect(Array.isArray(parsed.detail)).toBe(true);
  });
});
