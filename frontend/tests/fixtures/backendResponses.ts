/**
 * Real responses, captured from the backend's own response models.
 *
 * Copied verbatim from what the Python schemas serialise rather than written by hand, so
 * a schema here that passes its test is a schema that accepts what the server sends. A
 * fixture somebody invents tends to describe the contract as they remember it, which is
 * the same document being checked and therefore checks nothing.
 *
 * Two properties of the real output are load-bearing and easy to get wrong from memory:
 * an unset optional arrives as an explicit null rather than a missing key, and timestamps
 * carry microsecond precision with a trailing Z.
 *
 * To refresh: build each response model in a scratch script, print `model_dump_json()`,
 * and paste the result.
 */

export const knowledgeBaseFull = {
  id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
  user_id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
  name: 'Cloud Data Science',
  description: 'A description',
  subject: 'Data science',
  learning_goal: 'Pass the exam',
  preferred_language: 'en',
  explanation_level: 'INTERMEDIATE',
  exam_date: '2026-12-01',
  graph_enabled: true,
  active_index_version: 2,
  active_graph_version: 1,
  created_at: '2026-08-25T19:38:49.123456Z',
  updated_at: '2026-08-25T19:38:49.123456Z',
};

export const knowledgeBaseSparse = {
  id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
  user_id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
  name: 'Minimal',
  description: null,
  subject: null,
  learning_goal: null,
  preferred_language: 'en',
  explanation_level: 'INTRODUCTORY',
  exam_date: null,
  graph_enabled: false,
  active_index_version: 1,
  active_graph_version: 1,
  created_at: '2026-08-25T19:38:49.123456Z',
  updated_at: '2026-08-25T19:38:49.123456Z',
};

export const reindexAccepted = {
  knowledge_base_id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
  job_id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
  documents: 3,
  active_index_version: 1,
  target_index_version: 2,
};

export const documentUploaded = {
  document_id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
  status: 'PENDING',
  page_count: 62,
};

export const documentSparse = {
  id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
  knowledge_base_id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
  filename: 'book.pdf',
  content_type: 'application/pdf',
  byte_size: 1024,
  page_count: null,
  status: 'PENDING',
  title: null,
  checksum: null,
  language: 'en',
  failure_reason: null,
  created_at: '2026-08-25T19:38:49.123456Z',
  updated_at: '2026-08-25T19:38:49.123456Z',
  processed_at: null,
};

export const documentStatusSnapshotProcessing = {
  id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
  status: 'PROCESSING',
  page_count: null,
  failure_reason: null,
  updated_at: '2026-08-25T19:38:49.123456Z',
};

export const conversationNew = {
  id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
  knowledge_base_id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
  title: 'Chat',
  created_at: '2026-08-25T19:38:49.123456Z',
  updated_at: '2026-08-25T19:38:49.123456Z',
  active_document_id: null,
  active_page_number: null,
  active_figure_id: null,
  active_table_id: null,
};

export const assistantMessage = {
  id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
  conversation_id: '30b5e0f2-defb-4165-80fe-3cb7962bdf9c',
  role: 'ASSISTANT',
  status: 'COMPLETED',
  content: 'An answer',
  created_at: '2026-08-25T19:38:49.123456Z',
  updated_at: '2026-08-25T19:38:49.123456Z',
  rewritten_query: null,
  model_id: null,
  prompt_tokens: null,
  completion_tokens: null,
  finish_reason: null,
};

/** What the application raises: a message, and the trace id tying it to the server log. */
export const domainError = {
  detail: 'Widget not found',
  trace_id: 'fa3a77ce-b1b9-454d-b868-ffbe477d6367',
};

/**
 * What the web framework raises before the application is reached. Note the absent trace
 * id and the detail being a list, both of which a client modelling only the shape above
 * would choke on — while answering with the same 422 status the application uses.
 */
export const validationError = {
  detail: [
    {
      type: 'string_too_short',
      loc: ['body', 'title'],
      msg: 'String should have at least 1 character',
      input: '',
      ctx: { min_length: 1 },
    },
    {
      type: 'uuid_parsing',
      loc: ['body', 'active_document_id'],
      msg: 'Input should be a valid UUID, invalid character: found `n` at 1',
      input: 'not-a-uuid',
      ctx: { error: 'invalid character: found `n` at 1' },
    },
  ],
};
