import type { ApiClient } from '@/api/client';
import {
  FlashcardListSchema,
  FlashcardReviewResponseSchema,
  LearningProgressSchema,
  QuizAttemptResponseSchema,
  QuizResponseSchema,
  StudyPlanListSchema,
  StudyPlanResponseSchema,
  StudyTaskSchema,
  SummaryListSchema,
  SummaryResponseSchema,
  type FlashcardResponse,
  type FlashcardReviewResponse,
  type FlashcardSource,
  type LearningProgress,
  type QuizAttemptResponse,
  type QuizResponse,
  type ReviewRating,
  type StudyPlanResponse,
  type StudyTask,
  type StudyTaskStatus,
  type SummaryResponse,
  type SummaryType,
} from '@/schemas/study';

export class ApiStudyGateway {
  readonly #client: ApiClient;

  constructor(client: ApiClient) {
    this.#client = client;
  }

  // Summaries
  generateSummary = (
    kbId: string,
    summaryType: SummaryType,
    query = '',
    sectionIds: string[] = [],
  ): Promise<SummaryResponse> =>
    this.#client.request(SummaryResponseSchema, `/knowledge-bases/${kbId}/summaries`, {
      method: 'POST',
      body: { summary_type: summaryType, query, section_ids: sectionIds },
    });

  listSummaries = (kbId: string): Promise<SummaryResponse[]> =>
    this.#client.request(SummaryListSchema, `/knowledge-bases/${kbId}/summaries`);

  // Quizzes
  generateQuiz = (kbId: string, topic: string, nQuestions: number): Promise<QuizResponse> =>
    this.#client.request(QuizResponseSchema, `/knowledge-bases/${kbId}/quizzes`, {
      method: 'POST',
      body: { topic, n_questions: nQuestions },
    });

  getQuiz = (kbId: string, quizId: string): Promise<QuizResponse> =>
    this.#client.request(QuizResponseSchema, `/knowledge-bases/${kbId}/quizzes/${quizId}`);

  submitQuizAttempt = (
    kbId: string,
    quizId: string,
    answers: Record<string, string>,
  ): Promise<QuizAttemptResponse> =>
    this.#client.request(
      QuizAttemptResponseSchema,
      `/knowledge-bases/${kbId}/quizzes/${quizId}/attempts`,
      { method: 'POST', body: { answers } },
    );

  // Flashcards
  generateFlashcards = (
    kbId: string,
    source: FlashcardSource,
    query = '',
  ): Promise<FlashcardResponse[]> =>
    this.#client.request(FlashcardListSchema, `/knowledge-bases/${kbId}/flashcards`, {
      method: 'POST',
      body: { source, query },
    });

  listFlashcards = (kbId: string): Promise<FlashcardResponse[]> =>
    this.#client.request(FlashcardListSchema, `/knowledge-bases/${kbId}/flashcards`);

  reviewFlashcard = (
    kbId: string,
    cardId: string,
    rating: ReviewRating,
  ): Promise<FlashcardReviewResponse> =>
    this.#client.request(
      FlashcardReviewResponseSchema,
      `/knowledge-bases/${kbId}/flashcards/${cardId}/reviews`,
      { method: 'POST', body: { rating } },
    );

  // Study plans
  createStudyPlan = (
    kbId: string,
    examDate: string,
    availableHoursPerDay: number,
    chapters: string[],
    priorityTopics: string[],
  ): Promise<StudyPlanResponse> =>
    this.#client.request(StudyPlanResponseSchema, `/knowledge-bases/${kbId}/study-plans`, {
      method: 'POST',
      body: {
        exam_date: examDate,
        available_hours_per_day: availableHoursPerDay,
        chapters,
        priority_topics: priorityTopics,
      },
    });

  listStudyPlans = (kbId: string): Promise<StudyPlanResponse[]> =>
    this.#client.request(StudyPlanListSchema, `/knowledge-bases/${kbId}/study-plans`);

  updateTaskStatus = (
    kbId: string,
    planId: string,
    taskId: string,
    status: StudyTaskStatus,
  ): Promise<StudyTask> =>
    this.#client.request(
      StudyTaskSchema,
      `/knowledge-bases/${kbId}/study-plans/${planId}/tasks/${taskId}`,
      { method: 'PATCH', body: { status } },
    );

  // Progress
  getProgress = (kbId: string): Promise<LearningProgress> =>
    this.#client.request(LearningProgressSchema, `/knowledge-bases/${kbId}/progress`);
}
