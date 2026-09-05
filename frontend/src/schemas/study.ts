import { z } from 'zod';

// ── Enums ─────────────────────────────────────────────────────────────────────

export const SummaryTypeSchema = z.enum([
  'BRIEF',
  'DETAILED',
  'EXAMINATION_NOTES',
  'DEFINITIONS',
  'KEY_CONCEPTS',
  'FORMULA_LIST',
  'SECTION_OUTLINE',
]);
export type SummaryType = z.infer<typeof SummaryTypeSchema>;

export const QuestionTypeSchema = z.enum([
  'MULTIPLE_CHOICE',
  'TRUE_FALSE',
  'SHORT_ANSWER',
  'FILL_BLANK',
  'CHART_INTERPRETATION',
  'TABLE_INTERPRETATION',
]);
export type QuestionType = z.infer<typeof QuestionTypeSchema>;

export const FlashcardSourceSchema = z.enum([
  'DEFINITIONS',
  'KEY_CONCEPTS',
  'WEAK_TOPICS',
  'INCORRECT_ANSWERS',
]);
export type FlashcardSource = z.infer<typeof FlashcardSourceSchema>;

export const ReviewRatingSchema = z.enum(['AGAIN', 'HARD', 'GOOD', 'EASY']);
export type ReviewRating = z.infer<typeof ReviewRatingSchema>;

export const StudyTaskStatusSchema = z.enum(['PENDING', 'IN_PROGRESS', 'COMPLETED']);
export type StudyTaskStatus = z.infer<typeof StudyTaskStatusSchema>;

// ── Summaries ─────────────────────────────────────────────────────────────────

export const SummaryResponseSchema = z.object({
  id: z.string().uuid(),
  knowledge_base_id: z.string().uuid(),
  summary_type: SummaryTypeSchema,
  section_ids: z.array(z.string()),
  content: z.string(),
  created_at: z.string().datetime(),
});
export type SummaryResponse = z.infer<typeof SummaryResponseSchema>;

export const SummaryListSchema = z.array(SummaryResponseSchema);

// ── Quizzes ───────────────────────────────────────────────────────────────────

export const QuizQuestionSchema = z.object({
  id: z.string().uuid(),
  question_type: QuestionTypeSchema,
  question: z.string(),
  options: z.array(z.string()).nullable(),
  difficulty: z.string(),
  source_chunk_id: z.string().uuid().nullable(),
  document_id: z.string().uuid().nullable(),
  page_number: z.number().nullable(),
});
export type QuizQuestion = z.infer<typeof QuizQuestionSchema>;

export const QuizResponseSchema = z.object({
  id: z.string().uuid(),
  knowledge_base_id: z.string().uuid(),
  topic: z.string(),
  questions: z.array(QuizQuestionSchema),
  created_at: z.string().datetime(),
});
export type QuizResponse = z.infer<typeof QuizResponseSchema>;

export const QuizAttemptFeedbackSchema = z.object({
  correct: z.boolean(),
  correct_answer: z.string(),
  explanation: z.string(),
});
export type QuizAttemptFeedback = z.infer<typeof QuizAttemptFeedbackSchema>;

export const QuizAttemptResponseSchema = z.object({
  id: z.string().uuid(),
  quiz_id: z.string().uuid(),
  score: z.number(),
  correct_count: z.number(),
  total_count: z.number(),
  feedback: z.record(z.string(), QuizAttemptFeedbackSchema),
});
export type QuizAttemptResponse = z.infer<typeof QuizAttemptResponseSchema>;

// ── Flashcards ────────────────────────────────────────────────────────────────

export const FlashcardResponseSchema = z.object({
  id: z.string().uuid(),
  knowledge_base_id: z.string().uuid(),
  front: z.string(),
  back: z.string(),
  source: FlashcardSourceSchema,
  source_chunk_id: z.string().uuid().nullable(),
  document_id: z.string().uuid().nullable(),
  page_number: z.number().nullable(),
  created_at: z.string().datetime(),
});
export type FlashcardResponse = z.infer<typeof FlashcardResponseSchema>;

export const FlashcardListSchema = z.array(FlashcardResponseSchema);

export const FlashcardReviewResponseSchema = z.object({
  id: z.string().uuid(),
  flashcard_id: z.string().uuid(),
  rating: ReviewRatingSchema,
  reviewed_at: z.string().datetime(),
});
export type FlashcardReviewResponse = z.infer<typeof FlashcardReviewResponseSchema>;

// ── Study plans ───────────────────────────────────────────────────────────────

export const StudyTaskSchema = z.object({
  id: z.string().uuid(),
  title: z.string(),
  description: z.string(),
  due_date: z.string(),
  chapter_reference: z.string().nullable(),
  hours_allocated: z.number(),
  status: StudyTaskStatusSchema,
});
export type StudyTask = z.infer<typeof StudyTaskSchema>;

export const StudyPlanResponseSchema = z.object({
  id: z.string().uuid(),
  knowledge_base_id: z.string().uuid(),
  exam_date: z.string(),
  available_hours_per_day: z.number(),
  chapters: z.array(z.string()),
  priority_topics: z.array(z.string()),
  tasks: z.array(StudyTaskSchema),
  created_at: z.string().datetime(),
});
export type StudyPlanResponse = z.infer<typeof StudyPlanResponseSchema>;

export const StudyPlanListSchema = z.array(StudyPlanResponseSchema);

// ── Progress ──────────────────────────────────────────────────────────────────

export const LearningProgressSchema = z.object({
  knowledge_base_id: z.string().uuid(),
  topic_mastery: z.record(z.string(), z.number()),
  quiz_scores: z.array(z.record(z.string(), z.unknown())),
  flashcard_ratings: z.record(z.string(), z.number()),
  completed_chapters: z.array(z.string()),
  weak_concepts: z.array(z.string()),
  plan_completion: z.number(),
  last_review_date: z.string().datetime().nullable(),
});
export type LearningProgress = z.infer<typeof LearningProgressSchema>;

// ── Label maps ────────────────────────────────────────────────────────────────

export const SUMMARY_TYPE_LABELS: Record<SummaryType, string> = {
  BRIEF: 'Brief',
  DETAILED: 'Detailed',
  EXAMINATION_NOTES: 'Exam Notes',
  DEFINITIONS: 'Definitions',
  KEY_CONCEPTS: 'Key Concepts',
  FORMULA_LIST: 'Formula List',
  SECTION_OUTLINE: 'Section Outline',
};

export const FLASHCARD_SOURCE_LABELS: Record<FlashcardSource, string> = {
  DEFINITIONS: 'Definitions',
  KEY_CONCEPTS: 'Key Concepts',
  WEAK_TOPICS: 'Weak Topics',
  INCORRECT_ANSWERS: 'Incorrect Answers',
};

export const REVIEW_RATING_LABELS: Record<ReviewRating, string> = {
  AGAIN: 'Again',
  HARD: 'Hard',
  GOOD: 'Good',
  EASY: 'Easy',
};
