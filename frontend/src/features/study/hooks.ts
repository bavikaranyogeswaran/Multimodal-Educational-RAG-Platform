import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useApi } from '@/api/apiContext';
import { ApiStudyGateway } from '@/features/study/apiGateway';
import type { FlashcardSource, ReviewRating, StudyTaskStatus, SummaryType } from '@/schemas/study';

function useGateway() {
  return new ApiStudyGateway(useApi());
}

// ── Summaries ─────────────────────────────────────────────────────────────────

const summaryListKey = (kbId: string) => ['study', kbId, 'summaries'] as const;

export function useSummaries(kbId: string) {
  const gw = useGateway();
  return useQuery({
    queryKey: summaryListKey(kbId),
    queryFn: () => gw.listSummaries(kbId),
    staleTime: 5 * 60 * 1000,
  });
}

export function useGenerateSummary(kbId: string) {
  const gw = useGateway();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      summaryType,
      query,
    }: {
      summaryType: SummaryType;
      query: string;
    }) => gw.generateSummary(kbId, summaryType, query),
    onSuccess: () => void qc.invalidateQueries({ queryKey: summaryListKey(kbId) }),
  });
}

// ── Quizzes ───────────────────────────────────────────────────────────────────

export function useGenerateQuiz(kbId: string) {
  const gw = useGateway();
  return useMutation({
    mutationFn: ({ topic, nQuestions }: { topic: string; nQuestions: number }) =>
      gw.generateQuiz(kbId, topic, nQuestions),
  });
}

export function useSubmitQuizAttempt(kbId: string) {
  const gw = useGateway();
  return useMutation({
    mutationFn: ({ quizId, answers }: { quizId: string; answers: Record<string, string> }) =>
      gw.submitQuizAttempt(kbId, quizId, answers),
  });
}

// ── Flashcards ────────────────────────────────────────────────────────────────

const flashcardListKey = (kbId: string) => ['study', kbId, 'flashcards'] as const;

export function useFlashcards(kbId: string) {
  const gw = useGateway();
  return useQuery({
    queryKey: flashcardListKey(kbId),
    queryFn: () => gw.listFlashcards(kbId),
    staleTime: 5 * 60 * 1000,
  });
}

export function useGenerateFlashcards(kbId: string) {
  const gw = useGateway();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ source, query }: { source: FlashcardSource; query: string }) =>
      gw.generateFlashcards(kbId, source, query),
    onSuccess: () => void qc.invalidateQueries({ queryKey: flashcardListKey(kbId) }),
  });
}

export function useReviewFlashcard(kbId: string) {
  const gw = useGateway();
  return useMutation({
    mutationFn: ({ cardId, rating }: { cardId: string; rating: ReviewRating }) =>
      gw.reviewFlashcard(kbId, cardId, rating),
  });
}

// ── Study plans ───────────────────────────────────────────────────────────────

const planListKey = (kbId: string) => ['study', kbId, 'plans'] as const;

export function useStudyPlans(kbId: string) {
  const gw = useGateway();
  return useQuery({
    queryKey: planListKey(kbId),
    queryFn: () => gw.listStudyPlans(kbId),
    staleTime: 5 * 60 * 1000,
  });
}

export function useCreateStudyPlan(kbId: string) {
  const gw = useGateway();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      examDate,
      hoursPerDay,
      chapters,
      priorityTopics,
    }: {
      examDate: string;
      hoursPerDay: number;
      chapters: string[];
      priorityTopics: string[];
    }) => gw.createStudyPlan(kbId, examDate, hoursPerDay, chapters, priorityTopics),
    onSuccess: () => void qc.invalidateQueries({ queryKey: planListKey(kbId) }),
  });
}

export function useUpdateTaskStatus(kbId: string) {
  const gw = useGateway();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      planId,
      taskId,
      status,
    }: {
      planId: string;
      taskId: string;
      status: StudyTaskStatus;
    }) => gw.updateTaskStatus(kbId, planId, taskId, status),
    onSuccess: () => void qc.invalidateQueries({ queryKey: planListKey(kbId) }),
  });
}

// ── Progress ──────────────────────────────────────────────────────────────────

export function useProgress(kbId: string) {
  const gw = useGateway();
  return useQuery({
    queryKey: ['study', kbId, 'progress'] as const,
    queryFn: () => gw.getProgress(kbId),
    staleTime: 5 * 60 * 1000,
  });
}
