import type { Page, Route } from '@playwright/test';

// ── Stable UUIDs for fixture data ─────────────────────────────────────────────
// These must be real UUIDs; the Zod schemas in the app validate every id field.

// UUID v4 format: 8-4-4xxx-8xxx-12 (version nibble=4, variant nibble=8)
export const KB_ID        = 'e2e00000-0000-4000-8000-000000000001';
export const USER_ID      = 'e2e00000-0000-4000-8000-000000000002';
export const DOC_ID       = 'e2e00000-0000-4000-8000-000000000003';
export const CONV_ID      = 'e2e00000-0000-4000-8000-000000000004';
const MSG_USER_ID         = 'e2e00000-0000-4000-8000-000000000005';
const MSG_ASST_ID         = 'e2e00000-0000-4000-8000-000000000006';
const MEM_ID_1            = 'e2e00000-0000-4000-8000-000000000007';
const MEM_ID_2            = 'e2e00000-0000-4000-8000-000000000008';
const CONV_NEW_ID         = 'e2e00000-0000-4000-8000-000000000009';
const SUM_ID              = 'e2e00000-0000-4000-8000-00000000000a';

// ── JWT helpers ───────────────────────────────────────────────────────────────

/**
 * Build a fake JWT whose payload the Supabase JS client will accept.
 *
 * The client reads `exp` to decide whether to refresh. It does not verify the
 * signature on the browser side, so the third segment can be anything.
 */
function makeJwt(payload: object): string {
  const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
  return `${header}.${body}.fakesig`;
}

export const E2E_USER = {
  id: USER_ID,
  email: 'student@e2e.test',
};

export const ACCESS_TOKEN = makeJwt({
  sub: E2E_USER.id,
  email: E2E_USER.email,
  role: 'authenticated',
  aud: 'authenticated',
  iat: 1_000_000_000,
  exp: 9_999_999_999, // year 2286 — won't trigger refresh during tests
});

export function supabaseSession() {
  return {
    access_token: ACCESS_TOKEN,
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: 9_999_999_999,
    refresh_token: 'e2e-refresh-token',
    user: {
      id: E2E_USER.id,
      aud: 'authenticated',
      role: 'authenticated',
      email: E2E_USER.email,
      email_confirmed_at: '2024-01-01T00:00:00.000Z',
      phone: '',
      confirmed_at: '2024-01-01T00:00:00.000Z',
      last_sign_in_at: '2024-01-01T00:00:00.000Z',
      app_metadata: { provider: 'email', providers: ['email'] },
      user_metadata: {},
      identities: [],
      created_at: '2024-01-01T00:00:00.000Z',
      updated_at: '2024-01-01T00:00:00.000Z',
    },
  };
}

// ── Route helpers ─────────────────────────────────────────────────────────────

/**
 * Intercept all Supabase auth API calls.
 * POSTs to the token endpoint return a valid fake session; everything else returns {}.
 */
export async function mockSupabaseAuth(page: Page): Promise<void> {
  await page.route('http://supabase.e2e/**', async (route: Route) => {
    const req = route.request();
    if (req.method() === 'POST' && req.url().includes('/token')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(supabaseSession()),
      });
    } else {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
    }
  });
}

/**
 * Seed a pre-built Supabase session into localStorage before the page scripts run.
 *
 * The Supabase v2 storage key is `sb-${hostname.split('.')[0]}-auth-token`.
 * With VITE_SUPABASE_URL=http://supabase.e2e the key is `sb-supabase-auth-token`.
 * The far-future `expires_at` prevents any refresh attempt during the test.
 */
export async function seedAuth(page: Page): Promise<void> {
  const session = supabaseSession();
  await page.addInitScript(
    (args: { storageKey: string; value: string }) => {
      localStorage.setItem(args.storageKey, args.value);
    },
    {
      storageKey: 'sb-supabase-auth-token',
      value: JSON.stringify(session),
    },
  );
}

/** Register backend API route interceptors before page navigation. */
export async function mockApi(page: Page): Promise<void> {
  const T = '2026-01-01T00:00:00.000Z';

  const getRoutes: Record<string, unknown> = {
    '/api/v1/knowledge-bases': [
      {
        id: KB_ID,
        user_id: USER_ID,
        name: 'E2E Test KB',
        description: 'Created for end-to-end tests',
        subject: 'Testing',
        learning_goal: 'Cover all flows',
        preferred_language: 'en',
        explanation_level: 'INTERMEDIATE',
        exam_date: null,
        graph_enabled: true,
        active_index_version: 1,
        active_graph_version: 1,
        created_at: T,
        updated_at: T,
      },
    ],
    [`/api/v1/knowledge-bases/${KB_ID}/documents`]: [
      {
        id: DOC_ID,
        knowledge_base_id: KB_ID,
        filename: 'lecture-notes.pdf',
        content_type: 'application/pdf',
        byte_size: 512000,
        page_count: 42,
        status: 'COMPLETED',
        title: 'Lecture Notes',
        checksum: null,
        language: 'en',
        failure_reason: null,
        created_at: T,
        updated_at: T,
        processed_at: '2026-01-01T01:00:00.000Z',
      },
    ],
    [`/api/v1/knowledge-bases/${KB_ID}/conversations`]: [
      {
        id: CONV_ID,
        knowledge_base_id: KB_ID,
        title: 'E2E Conversation',
        created_at: T,
        updated_at: T,
        active_document_id: null,
        active_page_number: null,
        active_figure_id: null,
        active_table_id: null,
      },
    ],
    [`/api/v1/knowledge-bases/${KB_ID}/conversations/${CONV_ID}`]: {
      id: CONV_ID,
      knowledge_base_id: KB_ID,
      title: 'E2E Conversation',
      created_at: T,
      updated_at: T,
      active_document_id: null,
      active_page_number: null,
      active_figure_id: null,
      active_table_id: null,
    },
    [`/api/v1/knowledge-bases/${KB_ID}/conversations/${CONV_ID}/messages`]: [
      {
        id: MSG_USER_ID,
        conversation_id: CONV_ID,
        role: 'USER',
        status: 'COMPLETED',
        content: 'What is mitosis?',
        created_at: '2026-01-01T00:01:00.000Z',
        updated_at: '2026-01-01T00:01:00.000Z',
        rewritten_query: null,
        model_id: null,
        prompt_tokens: null,
        completion_tokens: null,
        finish_reason: null,
      },
      {
        id: MSG_ASST_ID,
        conversation_id: CONV_ID,
        role: 'ASSISTANT',
        status: 'COMPLETED',
        content: 'Mitosis is cell division producing two identical daughter cells.',
        created_at: '2026-01-01T00:01:01.000Z',
        updated_at: '2026-01-01T00:01:01.000Z',
        rewritten_query: 'What is mitosis?',
        model_id: 'gemma3:4b',
        prompt_tokens: 120,
        completion_tokens: 40,
        finish_reason: 'stop',
      },
    ],
    [`/api/v1/knowledge-bases/${KB_ID}/conversations/${CONV_ID}/citations/${MSG_ASST_ID}`]: [],
    [`/api/v1/knowledge-bases/${KB_ID}/memory`]: {
      facts: [
        {
          id: MEM_ID_1,
          key: 'Study goal',
          value: { goal: 'Pass the biology final' },
          memory_type: 'GOAL',
          status: 'ACTIVE',
          provenance: 10,
          confidence: 0.92,
          expires_at: null,
          created_at: T,
          updated_at: T,
        },
        {
          id: MEM_ID_2,
          key: 'Exam date',
          value: { date: '2026-12-15' },
          memory_type: 'EXAM_DATE',
          status: 'ACTIVE',
          provenance: 10,
          confidence: 1.0,
          expires_at: null,
          created_at: T,
          updated_at: T,
        },
      ],
    },
    [`/api/v1/knowledge-bases/${KB_ID}/flashcards`]: [],
    [`/api/v1/knowledge-bases/${KB_ID}/study-plans`]: [],
    [`/api/v1/knowledge-bases/${KB_ID}/progress`]: {
      knowledge_base_id: KB_ID,
      topic_mastery: { Mitosis: 0.75, Meiosis: 0.5 },
      quiz_scores: [
        { score: 0.8, topic: 'Cell division' },
        { score: 0.9, topic: 'Genetics' },
      ],
      flashcard_ratings: { GOOD: 5, EASY: 3, HARD: 2 },
      completed_chapters: ['Chapter 1', 'Chapter 2'],
      weak_concepts: ['Prophase', 'Crossing over'],
      plan_completion: 0.6,
      last_review_date: '2026-09-01T10:00:00.000Z',
    },
  };

  const createdSummaries: unknown[] = [];

  await page.route(/\/api\/v1\//, async (route: Route) => {
    const req = route.request();
    const method = req.method();
    const url = new URL(req.url());
    const pathname = url.pathname;

    if (method === 'GET') {
      if (pathname === `/api/v1/knowledge-bases/${KB_ID}/summaries`) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(createdSummaries),
        });
        return;
      }
      const body = getRoutes[pathname];
      if (body !== undefined) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(body),
        });
        return;
      }
    }

    if (method === 'POST' && pathname.endsWith('/stream')) {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache' },
        body: 'data: Mitosis\n\ndata:  is\n\ndata:  cell\n\ndata:  division.\n\ndata: [DONE]\n\n',
      });
      return;
    }

    if (method === 'POST' && pathname.endsWith('/conversations')) {
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: CONV_NEW_ID,
          knowledge_base_id: KB_ID,
          title: 'New chat',
          created_at: '2026-09-05T00:00:00.000Z',
          updated_at: '2026-09-05T00:00:00.000Z',
          active_document_id: null,
          active_page_number: null,
          active_figure_id: null,
          active_table_id: null,
        }),
      });
      return;
    }

    if (method === 'POST' && pathname.endsWith('/summaries')) {
      const newSummary = {
        id: SUM_ID,
        knowledge_base_id: KB_ID,
        summary_type: 'BRIEF',
        section_ids: [],
        content:
          'Mitosis is the process by which a cell divides into two identical daughter cells.',
        created_at: '2026-09-05T00:00:00.000Z',
      };
      createdSummaries.push(newSummary);
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(newSummary),
      });
      return;
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
}
