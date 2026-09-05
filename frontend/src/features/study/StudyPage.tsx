import { useState } from 'react';
import { Link, useLocation, useParams } from 'react-router';

import {
  useCreateStudyPlan,
  useFlashcards,
  useGenerateFlashcards,
  useGenerateQuiz,
  useGenerateSummary,
  useProgress,
  useReviewFlashcard,
  useStudyPlans,
  useSubmitQuizAttempt,
  useSummaries,
  useUpdateTaskStatus,
} from '@/features/study/hooks';
import styles from '@/features/study/study.module.css';
import {
  FLASHCARD_SOURCE_LABELS,
  REVIEW_RATING_LABELS,
  SUMMARY_TYPE_LABELS,
  type FlashcardResponse,
  type FlashcardSource,
  type QuizAttemptResponse,
  type QuizResponse,
  type ReviewRating,
  type StudyPlanResponse,
  type StudyTask,
  type StudyTaskStatus,
  type SummaryResponse,
  type SummaryType,
} from '@/schemas/study';

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function diffClass(d: string): string {
  const lower = d.toLowerCase();
  if (lower === 'easy') return styles.diffEasy ?? '';
  if (lower === 'hard') return styles.diffHard ?? '';
  return styles.diffMedium ?? '';
}

// ── Summaries tab ─────────────────────────────────────────────────────────────

function SummaryTab({ kbId }: { kbId: string }) {
  const [type, setType] = useState<SummaryType>('BRIEF');
  const [query, setQuery] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: summaries = [], isLoading } = useSummaries(kbId);
  const generateMut = useGenerateSummary(kbId);

  function handleGenerate() {
    generateMut.mutate({ summaryType: type, query });
  }

  return (
    <>
      <div className={styles.form}>
        <div className={styles.formRow}>
          <label className={styles.label}>Summary type</label>
          <select
            className={styles.select}
            value={type}
            onChange={(e) => setType(e.target.value as SummaryType)}
          >
            {(Object.keys(SUMMARY_TYPE_LABELS) as SummaryType[]).map((t) => (
              <option key={t} value={t}>{SUMMARY_TYPE_LABELS[t]}</option>
            ))}
          </select>
        </div>
        <div className={styles.formRow}>
          <label className={styles.label}>Topic hint (optional)</label>
          <input
            className={styles.input}
            placeholder="e.g. oxidative phosphorylation"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className={styles.formActions}>
          <button
            className={styles.btnPrimary}
            onClick={handleGenerate}
            disabled={generateMut.isPending}
          >
            {generateMut.isPending ? 'Generating…' : 'Generate'}
          </button>
        </div>
        {generateMut.isError && (
          <p style={{ color: 'var(--danger)', fontSize: '0.82rem', margin: 0 }}>
            {(generateMut.error as Error).message}
          </p>
        )}
      </div>

      {isLoading && <div className={styles.empty}><span>Loading…</span></div>}

      {!isLoading && summaries.length === 0 && (
        <div className={styles.empty}>
          <p>No summaries yet.</p>
          <p>Generate one above to get started.</p>
        </div>
      )}

      {summaries.map((s: SummaryResponse) => {
        const expanded = expandedId === s.id;
        return (
          <div key={s.id} className={styles.summaryCard}>
            <div
              className={styles.summaryCardHeader}
              onClick={() => setExpandedId(expanded ? null : s.id)}
            >
              <span className={styles.summaryBadge}>{SUMMARY_TYPE_LABELS[s.summary_type]}</span>
              <span className={styles.summaryDate}>{formatDate(s.created_at)}</span>
              <span className={styles.summaryChevron}>{expanded ? '▲' : '▼'}</span>
            </div>
            {expanded && (
              <div className={styles.summaryContent}>{s.content}</div>
            )}
          </div>
        );
      })}
    </>
  );
}

// ── Quiz tab ──────────────────────────────────────────────────────────────────

type QuizState = 'setup' | 'taking' | 'results';

function QuizTab({ kbId }: { kbId: string }) {
  const [quizState, setQuizState] = useState<QuizState>('setup');
  const [topic, setTopic] = useState('');
  const [nQuestions, setNQuestions] = useState(5);
  const [activeQuiz, setActiveQuiz] = useState<QuizResponse | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<QuizAttemptResponse | null>(null);

  const generateMut = useGenerateQuiz(kbId);
  const submitMut = useSubmitQuizAttempt(kbId);

  async function handleGenerate() {
    if (!topic.trim()) return;
    const quiz = await generateMut.mutateAsync({ topic: topic.trim(), nQuestions });
    setActiveQuiz(quiz);
    setAnswers({});
    setResult(null);
    setQuizState('taking');
  }

  async function handleSubmit() {
    if (!activeQuiz) return;
    const res = await submitMut.mutateAsync({ quizId: activeQuiz.id, answers });
    setResult(res);
    setQuizState('results');
  }

  function handleReset() {
    setQuizState('setup');
    setActiveQuiz(null);
    setAnswers({});
    setResult(null);
  }

  if (quizState === 'setup') {
    return (
      <div className={styles.form}>
        <div className={styles.formRow}>
          <label className={styles.label}>Topic</label>
          <input
            className={styles.input}
            placeholder="e.g. Krebs cycle"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          />
        </div>
        <div className={styles.formRow}>
          <label className={styles.label}>Number of questions</label>
          <div className={styles.numRow}>
            <input
              type="number"
              className={`${styles.input} ${styles.numInput}`}
              min={1}
              max={20}
              value={nQuestions}
              onChange={(e) => setNQuestions(Math.min(20, Math.max(1, Number(e.target.value))))}
            />
          </div>
        </div>
        <div className={styles.formActions}>
          <button
            className={styles.btnPrimary}
            onClick={handleGenerate}
            disabled={generateMut.isPending || !topic.trim()}
          >
            {generateMut.isPending ? 'Generating…' : 'Generate quiz'}
          </button>
        </div>
        {generateMut.isError && (
          <p style={{ color: 'var(--danger)', fontSize: '0.82rem', margin: 0 }}>
            {(generateMut.error as Error).message}
          </p>
        )}
      </div>
    );
  }

  if (quizState === 'taking' && activeQuiz) {
    return (
      <>
        <div className={styles.quizMeta}>
          <p className={styles.quizTopic}>{activeQuiz.topic}</p>
          <button className={styles.btnGhost} onClick={handleReset}>Start over</button>
        </div>

        {activeQuiz.questions.map((q, i) => (
          <div key={q.id} className={styles.questionCard}>
            <div className={styles.questionNumber}>
              Question {i + 1} of {activeQuiz.questions.length}
              <span className={`${styles.difficultyBadge} ${diffClass(q.difficulty)}`}>
                {q.difficulty}
              </span>
            </div>
            <p className={styles.questionText}>{q.question}</p>

            {q.options && q.options.length > 0 ? (
              <div className={styles.optionList}>
                {q.options.map((opt) => (
                  <label key={opt} className={styles.optionLabel}>
                    <input
                      type="radio"
                      name={q.id}
                      value={opt}
                      checked={answers[q.id] === opt}
                      onChange={() => setAnswers((prev) => ({ ...prev, [q.id]: opt }))}
                    />
                    {opt}
                  </label>
                ))}
              </div>
            ) : (
              <input
                className={`${styles.input} ${styles.textAnswer}`}
                placeholder="Your answer…"
                value={answers[q.id] ?? ''}
                onChange={(e) => setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
              />
            )}
          </div>
        ))}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '1rem' }}>
          <button className={styles.btnGhost} onClick={handleReset}>Cancel</button>
          <button
            className={styles.btnPrimary}
            onClick={handleSubmit}
            disabled={submitMut.isPending}
          >
            {submitMut.isPending ? 'Submitting…' : 'Submit answers'}
          </button>
        </div>
      </>
    );
  }

  if (quizState === 'results' && result && activeQuiz) {
    const pct = Math.round(result.score * 100);
    return (
      <>
        <div className={styles.scoreRow}>
          <span className={styles.scoreBig}>{result.correct_count}</span>
          <span className={styles.scoreOf}>/ {result.total_count} correct — {pct}%</span>
        </div>

        {activeQuiz.questions.map((q, i) => {
          const fb = result.feedback[q.id];
          if (!fb) return null;
          return (
            <div key={q.id} className={styles.feedbackCard}>
              <div className={styles.feedbackHeader}>
                <span className={styles.feedbackIcon}>{fb.correct ? '✅' : '❌'}</span>
                <span className={styles.feedbackQuestion}>
                  {i + 1}. {q.question}
                </span>
              </div>
              <p className={styles.feedbackDetail}>
                <strong>Correct answer:</strong> {fb.correct_answer}
                <br />
                {fb.explanation}
              </p>
            </div>
          );
        })}

        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
          <button className={styles.btnPrimary} onClick={handleReset}>New quiz</button>
        </div>
      </>
    );
  }

  return null;
}

// ── Flashcards tab ────────────────────────────────────────────────────────────

type FlashState = 'setup' | 'reviewing' | 'done';

function FlashcardsTab({ kbId }: { kbId: string }) {
  const [flashState, setFlashState] = useState<FlashState>('setup');
  const [source, setSource] = useState<FlashcardSource>('DEFINITIONS');
  const [query, setQuery] = useState('');
  const [deck, setDeck] = useState<FlashcardResponse[]>([]);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [rated, setRated] = useState<Record<string, ReviewRating>>({});

  const { data: existingCards = [], isLoading } = useFlashcards(kbId);
  const generateMut = useGenerateFlashcards(kbId);
  const reviewMut = useReviewFlashcard(kbId);

  function startReview(cards: FlashcardResponse[]) {
    setDeck(cards);
    setCurrentIdx(0);
    setFlipped(false);
    setRated({});
    setFlashState('reviewing');
  }

  async function handleGenerate() {
    const cards = await generateMut.mutateAsync({ source, query });
    startReview(cards);
  }

  async function handleRating(rating: ReviewRating) {
    const card = deck[currentIdx];
    if (!card) return;
    await reviewMut.mutateAsync({ cardId: card.id, rating });
    setRated((prev) => ({ ...prev, [card.id]: rating }));
    const next = currentIdx + 1;
    if (next >= deck.length) {
      setFlashState('done');
    } else {
      setCurrentIdx(next);
      setFlipped(false);
    }
  }

  if (flashState === 'setup') {
    return (
      <>
        <div className={styles.form}>
          <div className={styles.formRow}>
            <label className={styles.label}>Source</label>
            <select
              className={styles.select}
              value={source}
              onChange={(e) => setSource(e.target.value as FlashcardSource)}
            >
              {(Object.keys(FLASHCARD_SOURCE_LABELS) as FlashcardSource[]).map((s) => (
                <option key={s} value={s}>{FLASHCARD_SOURCE_LABELS[s]}</option>
              ))}
            </select>
          </div>
          <div className={styles.formRow}>
            <label className={styles.label}>Topic hint (optional)</label>
            <input
              className={styles.input}
              placeholder="e.g. enzymes"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div className={styles.formActions}>
            <button
              className={styles.btnPrimary}
              onClick={handleGenerate}
              disabled={generateMut.isPending}
            >
              {generateMut.isPending ? 'Generating…' : 'Generate cards'}
            </button>
          </div>
          {generateMut.isError && (
            <p style={{ color: 'var(--danger)', fontSize: '0.82rem', margin: 0 }}>
              {(generateMut.error as Error).message}
            </p>
          )}
        </div>

        {!isLoading && existingCards.length > 0 && (
          <>
            <p className={styles.sectionHeading}>Existing deck — {existingCards.length} cards</p>
            <button
              className={styles.btnGhost}
              onClick={() => startReview(existingCards)}
            >
              Review existing deck
            </button>
          </>
        )}
      </>
    );
  }

  if (flashState === 'reviewing') {
    const card = deck[currentIdx];
    if (!card) return null;
    return (
      <>
        <p className={styles.deckProgress}>Card {currentIdx + 1} of {deck.length}</p>

        <div className={styles.cardDeck}>
          <div
            className={`${styles.flashcard} ${flipped ? styles.flashcardFlipped : ''}`}
            onClick={() => setFlipped((f) => !f)}
          >
            <div className={styles.flashcardFace}>
              <p className={styles.flashcardHint}>Question — tap to flip</p>
              <p className={styles.flashcardText}>{card.front}</p>
            </div>
            <div className={`${styles.flashcardFace} ${styles.flashcardBack}`}>
              <p className={styles.flashcardHint}>Answer</p>
              <p className={styles.flashcardText}>{card.back}</p>
            </div>
          </div>
        </div>

        <div className={styles.ratingRow}>
          {(['AGAIN', 'HARD', 'GOOD', 'EASY'] as ReviewRating[]).map((r) => {
            const cls = {
              AGAIN: styles.ratingAgain,
              HARD: styles.ratingHard,
              GOOD: styles.ratingGood,
              EASY: styles.ratingEasy,
            }[r];
            return (
              <button
                key={r}
                className={`${styles.ratingBtn} ${cls}`}
                disabled={reviewMut.isPending || !flipped}
                onClick={() => handleRating(r)}
              >
                {REVIEW_RATING_LABELS[r]}
              </button>
            );
          })}
        </div>
        {!flipped && (
          <p style={{ textAlign: 'center', fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>
            Flip the card before rating
          </p>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1.5rem' }}>
          <button className={styles.btnGhost} onClick={() => setFlashState('setup')}>
            Exit review
          </button>
        </div>
      </>
    );
  }

  if (flashState === 'done') {
    const counts = Object.values(rated).reduce<Record<string, number>>((acc, r) => {
      acc[r] = (acc[r] ?? 0) + 1;
      return acc;
    }, {});
    return (
      <div className={styles.deckDone}>
        <p className={styles.deckDoneTitle}>Deck complete!</p>
        <p>Reviewed {deck.length} cards</p>
        {(['AGAIN', 'HARD', 'GOOD', 'EASY'] as ReviewRating[]).map((r) =>
          counts[r] ? (
            <p key={r} style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              {REVIEW_RATING_LABELS[r]}: {counts[r]}
            </p>
          ) : null,
        )}
        <button
          className={styles.btnPrimary}
          style={{ marginTop: '1.25rem' }}
          onClick={() => setFlashState('setup')}
        >
          Back to deck
        </button>
      </div>
    );
  }

  return null;
}

// ── Study plan tab ────────────────────────────────────────────────────────────

function nextStatus(s: StudyTaskStatus): StudyTaskStatus {
  if (s === 'PENDING') return 'IN_PROGRESS';
  if (s === 'IN_PROGRESS') return 'COMPLETED';
  return 'PENDING';
}

function statusClass(s: StudyTaskStatus): string {
  if (s === 'IN_PROGRESS') return styles.taskStatusInProgress ?? '';
  if (s === 'COMPLETED') return styles.taskStatusCompleted ?? '';
  return styles.taskStatusPending ?? '';
}

function PlanView({
  plan,
  kbId,
}: {
  plan: StudyPlanResponse;
  kbId: string;
}) {
  const updateMut = useUpdateTaskStatus(kbId);

  // Group tasks by due_date
  const groups: Record<string, StudyTask[]> = {};
  for (const task of plan.tasks) {
    if (!groups[task.due_date]) groups[task.due_date] = [];
    groups[task.due_date]!.push(task);
  }
  const sortedDates = Object.keys(groups).sort();

  return (
    <div className={styles.planCard}>
      <div className={styles.planMeta}>
        <span><span className={styles.planMetaLabel}>Exam</span> {plan.exam_date}</span>
        <span><span className={styles.planMetaLabel}>Hours/day</span> {plan.available_hours_per_day}</span>
        <span><span className={styles.planMetaLabel}>Chapters</span> {plan.chapters.join(', ')}</span>
        {plan.priority_topics.length > 0 && (
          <span><span className={styles.planMetaLabel}>Priority</span> {plan.priority_topics.join(', ')}</span>
        )}
      </div>

      {sortedDates.map((date) => (
        <div key={date} className={styles.taskGroup}>
          <p className={styles.taskGroupDate}>{formatDate(date)}</p>
          {groups[date]!.map((task) => (
            <div key={task.id} className={styles.taskRow}>
              <button
                className={`${styles.taskStatusBtn} ${statusClass(task.status)}`}
                title={`Mark as ${nextStatus(task.status)}`}
                disabled={updateMut.isPending}
                onClick={() =>
                  updateMut.mutate({ planId: plan.id, taskId: task.id, status: nextStatus(task.status) })
                }
              />
              <div className={styles.taskBody}>
                <p className={`${styles.taskTitle} ${task.status === 'COMPLETED' ? styles.taskTitleDone : ''}`}>
                  {task.title}
                </p>
                <p className={styles.taskDesc}>{task.description}</p>
              </div>
              <span className={styles.taskHours}>{task.hours_allocated}h</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function StudyPlanTab({ kbId }: { kbId: string }) {
  const [examDate, setExamDate] = useState('');
  const [hoursPerDay, setHoursPerDay] = useState(2);
  const [chaptersRaw, setChaptersRaw] = useState('');
  const [topicsRaw, setTopicsRaw] = useState('');

  const { data: plans = [], isLoading } = useStudyPlans(kbId);
  const createMut = useCreateStudyPlan(kbId);

  async function handleCreate() {
    const chapters = chaptersRaw.split('\n').map((s) => s.trim()).filter((s): s is string => s.length > 0);
    const priorityTopics = topicsRaw.split('\n').map((s) => s.trim()).filter((s): s is string => s.length > 0);
    if (!examDate || chapters.length === 0) return;
    await createMut.mutateAsync({ examDate, hoursPerDay, chapters, priorityTopics });
  }

  return (
    <>
      <div className={styles.form}>
        <div style={{ display: 'grid', gap: '0.85rem', gridTemplateColumns: '1fr 1fr' }}>
          <div className={styles.formRow}>
            <label className={styles.label}>Exam date</label>
            <input
              type="date"
              className={styles.input}
              value={examDate}
              onChange={(e) => setExamDate(e.target.value)}
            />
          </div>
          <div className={styles.formRow}>
            <label className={styles.label}>Hours available per day</label>
            <input
              type="number"
              className={`${styles.input} ${styles.numInput}`}
              min={0.5}
              max={24}
              step={0.5}
              value={hoursPerDay}
              onChange={(e) => setHoursPerDay(Number(e.target.value))}
            />
          </div>
        </div>
        <div className={styles.formRow}>
          <label className={styles.label}>Chapters (one per line)</label>
          <textarea
            className={styles.textarea}
            placeholder="Chapter 1: Cell Biology&#10;Chapter 2: Genetics&#10;Chapter 3: Metabolism"
            value={chaptersRaw}
            onChange={(e) => setChaptersRaw(e.target.value)}
          />
        </div>
        <div className={styles.formRow}>
          <label className={styles.label}>Priority topics (one per line, optional)</label>
          <textarea
            className={styles.textarea}
            style={{ minHeight: '60px' }}
            placeholder="Krebs cycle&#10;DNA replication"
            value={topicsRaw}
            onChange={(e) => setTopicsRaw(e.target.value)}
          />
        </div>
        <div className={styles.formActions}>
          <button
            className={styles.btnPrimary}
            onClick={handleCreate}
            disabled={createMut.isPending || !examDate || !chaptersRaw.trim()}
          >
            {createMut.isPending ? 'Creating…' : 'Create plan'}
          </button>
        </div>
        {createMut.isError && (
          <p style={{ color: 'var(--danger)', fontSize: '0.82rem', margin: 0 }}>
            {(createMut.error as Error).message}
          </p>
        )}
      </div>

      {isLoading && <div className={styles.empty}><span>Loading…</span></div>}
      {!isLoading && plans.length === 0 && (
        <div className={styles.empty}>
          <p>No study plans yet.</p>
          <p>Fill in the form above to generate your first plan.</p>
        </div>
      )}

      {plans.map((plan: StudyPlanResponse) => (
        <PlanView key={plan.id} plan={plan} kbId={kbId} />
      ))}
    </>
  );
}

// ── Progress tab ──────────────────────────────────────────────────────────────

function ProgressTab({ kbId }: { kbId: string }) {
  const { data: progress, isLoading } = useProgress(kbId);

  if (isLoading) return <div className={styles.empty}><span>Loading…</span></div>;
  if (!progress) return <div className={styles.empty}><p>No progress data yet.</p></div>;

  const masteryEntries = Object.entries(progress.topic_mastery);
  const planPct = Math.round(progress.plan_completion * 100);

  return (
    <div className={styles.progressGrid}>
      {/* Plan completion */}
      <div className={styles.progressCard}>
        <p className={styles.progressCardTitle}>Plan completion</p>
        <p className={styles.planCompletion}>{planPct}%</p>
        <div className={styles.planBar}>
          <div className={styles.planBarFill} style={{ width: `${planPct}%` }} />
        </div>
        {progress.completed_chapters.length > 0 && (
          <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', margin: '0.5rem 0 0' }}>
            {progress.completed_chapters.length} chapter{progress.completed_chapters.length !== 1 ? 's' : ''} done
          </p>
        )}
      </div>

      {/* Topic mastery */}
      {masteryEntries.length > 0 && (
        <div className={styles.progressCard}>
          <p className={styles.progressCardTitle}>Topic mastery</p>
          {masteryEntries.map(([topic, score]) => (
            <div key={topic} className={styles.masterItem}>
              <span className={styles.masterLabel} title={topic}>{topic}</span>
              <div className={styles.masterBar}>
                <div className={styles.masterFill} style={{ width: `${Math.round(score * 100)}%` }} />
              </div>
              <span className={styles.masterPct}>{Math.round(score * 100)}%</span>
            </div>
          ))}
        </div>
      )}

      {/* Quiz scores */}
      {progress.quiz_scores.length > 0 && (
        <div className={styles.progressCard}>
          <p className={styles.progressCardTitle}>Quiz scores</p>
          <div className={styles.scoreList}>
            {progress.quiz_scores.slice(-8).map((entry, i) => {
              const raw = typeof entry['score'] === 'number' ? entry['score'] : 0;
              const pct = Math.round(raw * 100);
              return (
                <div key={i} className={styles.scoreRow2}>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', width: '1.5rem' }}>
                    {i + 1}
                  </span>
                  <div className={styles.scoreBar}>
                    <div className={styles.scoreFill} style={{ width: `${pct}%` }} />
                  </div>
                  <span className={styles.scorePct}>{pct}%</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Flashcard ratings */}
      {Object.keys(progress.flashcard_ratings).length > 0 && (
        <div className={styles.progressCard}>
          <p className={styles.progressCardTitle}>Flashcard ratings</p>
          {Object.entries(progress.flashcard_ratings).map(([rating, count]) => (
            <div key={rating} className={styles.masterItem}>
              <span className={styles.masterLabel}>{rating}</span>
              <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text)' }}>{String(count)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Weak concepts */}
      {progress.weak_concepts.length > 0 && (
        <div className={styles.progressCard}>
          <p className={styles.progressCardTitle}>Weak concepts</p>
          <div className={styles.tagList}>
            {progress.weak_concepts.map((c) => (
              <span key={c} className={styles.tag}>{c}</span>
            ))}
          </div>
        </div>
      )}

      {/* Last review */}
      {progress.last_review_date && (
        <div className={styles.progressCard}>
          <p className={styles.progressCardTitle}>Last review</p>
          <p className={styles.bigStat} style={{ fontSize: '1rem', fontWeight: 500 }}>
            {formatDate(progress.last_review_date)}
          </p>
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'summaries', label: 'Summaries' },
  { id: 'quiz', label: 'Quiz' },
  { id: 'flashcards', label: 'Flashcards' },
  { id: 'plan', label: 'Study Plan' },
  { id: 'progress', label: 'Progress' },
] as const;

type TabId = (typeof TABS)[number]['id'];

export function StudyPage() {
  const { kbId } = useParams<{ kbId: string }>();
  const loc = useLocation();
  const kbName = (loc.state as { kbName?: string } | null)?.kbName ?? 'Knowledge Base';

  const [activeTab, setActiveTab] = useState<TabId>('summaries');

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Link
          to={`/knowledge-bases/${kbId}`}
          state={{ kbName }}
          className={styles.backLink}
        >
          ← {kbName}
        </Link>
        <h1 className={styles.title}>Study</h1>
      </header>

      <nav className={styles.tabs}>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`${styles.tab} ${activeTab === t.id ? styles.tabActive : ''}`}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className={styles.body}>
        {activeTab === 'summaries' && <SummaryTab kbId={kbId!} />}
        {activeTab === 'quiz' && <QuizTab kbId={kbId!} />}
        {activeTab === 'flashcards' && <FlashcardsTab kbId={kbId!} />}
        {activeTab === 'plan' && <StudyPlanTab kbId={kbId!} />}
        {activeTab === 'progress' && <ProgressTab kbId={kbId!} />}
      </div>
    </div>
  );
}
