/**
 * End-to-end tests covering the primary user flows.
 *
 * Auth strategy:
 *  - Sign-in test: mock the Supabase token endpoint, sign in via the UI form.
 *  - All other tests: seed a pre-built session in localStorage (via addInitScript) so each
 *    test starts already authenticated without repeating the sign-in flow.
 *
 * Backend calls are intercepted via page.route() and answered with fixture data so the
 * tests run without a live FastAPI or database process.
 */

import { expect, test } from '@playwright/test';

import { CONV_ID, KB_ID, mockApi, mockSupabaseAuth, seedAuth } from './helpers/routes';

// ── Authentication ─────────────────────────────────────────────────────────────

test.describe('authentication', () => {
  test('unauthenticated root redirects to sign-in', async ({ page }) => {
    await mockSupabaseAuth(page);
    await mockApi(page);
    await page.goto('/');
    await expect(page).toHaveURL(/\/sign-in/, { timeout: 8000 });
    await expect(page.getByRole('heading', { name: /sign in/i })).toBeVisible();
  });

  test('sign-in form submits credentials and lands on knowledge base list', async ({ page }) => {
    await mockSupabaseAuth(page);
    await mockApi(page);

    await page.goto('/sign-in');
    await page.getByLabel('Email').fill('student@e2e.test');
    await page.getByLabel('Password').fill('pass1234');
    await page.getByRole('button', { name: 'Sign in' }).click();

    await expect(page.getByText('E2E Test KB')).toBeVisible({ timeout: 10_000 });
  });
});

// ── Knowledge bases ─────────────────────────────────────────────────────────────

test.describe('knowledge bases', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuth(page);
    await mockSupabaseAuth(page);
    await mockApi(page);
  });

  test('lists knowledge bases on the home page', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('E2E Test KB')).toBeVisible({ timeout: 8000 });
  });

  test('navigates into a knowledge base and shows documents', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: 'Documents' }).click();
    await expect(page).toHaveURL(new RegExp(`/knowledge-bases/${KB_ID}`), { timeout: 8000 });
    await expect(page.getByText('lecture-notes.pdf')).toBeVisible({ timeout: 8000 });
  });
});

// ── Documents ─────────────────────────────────────────────────────────────────

test.describe('documents', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuth(page);
    await mockSupabaseAuth(page);
    await mockApi(page);
  });

  test('shows document list with filename and page count', async ({ page }) => {
    await page.goto(`/knowledge-bases/${KB_ID}`);
    await expect(page.getByText('lecture-notes.pdf')).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('42')).toBeVisible();
  });
});

// ── Conversations ─────────────────────────────────────────────────────────────

test.describe('conversations', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuth(page);
    await mockSupabaseAuth(page);
    await mockApi(page);
  });

  test('shows conversation list', async ({ page }) => {
    await page.goto(`/knowledge-bases/${KB_ID}/conversations`);
    await expect(page.getByText('E2E Conversation')).toBeVisible({ timeout: 8000 });
  });

  test('opens an existing conversation and shows messages', async ({ page }) => {
    await page.goto(`/knowledge-bases/${KB_ID}/conversations/${CONV_ID}`);
    await expect(page.getByText('What is mitosis?')).toBeVisible({ timeout: 8000 });
    await expect(
      page.getByText('Mitosis is cell division producing two identical daughter cells.'),
    ).toBeVisible();
  });

  test('sends a message and displays the streamed response', async ({ page }) => {
    await page.goto(`/knowledge-bases/${KB_ID}/conversations/${CONV_ID}`);
    await expect(page.getByText('What is mitosis?')).toBeVisible({ timeout: 8000 });

    // Find the chat input (look for a textarea or input with a send action)
    const input = page.getByRole('textbox').last();
    await input.fill('Tell me about meiosis');
    await input.press('Enter');

    // Wait for the streamed response — first token is "Mitosis"
    await expect(page.getByText(/Mitosis.*cell.*division/)).toBeVisible({ timeout: 10_000 });
  });
});

// ── Memory ─────────────────────────────────────────────────────────────────────

test.describe('memory', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuth(page);
    await mockSupabaseAuth(page);
    await mockApi(page);
  });

  test('shows memory facts grouped by type', async ({ page }) => {
    await page.goto(`/knowledge-bases/${KB_ID}/memory`);
    await expect(page.getByText('Study goal')).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Pass the biology final')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Exam date' })).toBeVisible();
    await expect(page.getByText('2026-12-15')).toBeVisible();
  });

  test('dispute and delete buttons are present', async ({ page }) => {
    await page.goto(`/knowledge-bases/${KB_ID}/memory`);
    await expect(page.getByText('Study goal')).toBeVisible({ timeout: 8000 });
    await expect(page.getByRole('button', { name: 'Dispute' }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Delete' }).first()).toBeVisible();
  });
});

// ── Study page ──────────────────────────────────────────────────────────────────

test.describe('study', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuth(page);
    await mockSupabaseAuth(page);
    await mockApi(page);
  });

  test('shows all five tabs', async ({ page }) => {
    await page.goto(`/knowledge-bases/${KB_ID}/study`);
    await expect(page.getByRole('button', { name: 'Summaries' })).toBeVisible({ timeout: 8000 });
    await expect(page.getByRole('button', { name: 'Quiz' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Flashcards' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Study Plan' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Progress' })).toBeVisible();
  });

  test('summaries tab generates a summary and shows it', async ({ page }) => {
    await page.goto(`/knowledge-bases/${KB_ID}/study`);
    await expect(page.getByRole('button', { name: /generate/i })).toBeVisible({ timeout: 8000 });
    await page.getByRole('button', { name: /generate/i }).click();
    // Wait for the summary card to appear, then click the header to expand it
    await expect(page.getByText(/Sep 5, 2026/)).toBeVisible({ timeout: 8000 });
    await page.getByText(/Sep 5, 2026/).click();
    await expect(
      page.getByText('Mitosis is the process by which a cell divides into two identical daughter cells.'),
    ).toBeVisible({ timeout: 3000 });
  });

  test('progress tab shows topic mastery and weak concepts', async ({ page }) => {
    await page.goto(`/knowledge-bases/${KB_ID}/study`);
    await page.getByRole('button', { name: 'Progress' }).click();
    await expect(page.getByText('Mitosis')).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Meiosis')).toBeVisible();
    await expect(page.getByText('Prophase')).toBeVisible();
  });

  test('quiz tab shows topic input and generate button', async ({ page }) => {
    await page.goto(`/knowledge-bases/${KB_ID}/study`);
    await page.getByRole('button', { name: 'Quiz' }).click();
    await expect(page.getByLabel('Topic')).toBeVisible({ timeout: 8000 });
    await expect(page.getByRole('button', { name: /generate quiz/i })).toBeVisible();
  });

  test('flashcards tab shows source selector and generate button', async ({ page }) => {
    await page.goto(`/knowledge-bases/${KB_ID}/study`);
    await page.getByRole('button', { name: 'Flashcards' }).click();
    await expect(page.getByLabel('Source')).toBeVisible({ timeout: 8000 });
    await expect(page.getByRole('button', { name: /generate cards/i })).toBeVisible();
  });

  test('study plan tab shows plan creation form', async ({ page }) => {
    await page.goto(`/knowledge-bases/${KB_ID}/study`);
    await page.getByRole('button', { name: 'Study Plan' }).click();
    await expect(page.getByLabel('Exam date')).toBeVisible({ timeout: 8000 });
    await expect(page.getByLabel('Chapters (one per line)')).toBeVisible();
    await expect(page.getByRole('button', { name: /create plan/i })).toBeVisible();
  });
});
