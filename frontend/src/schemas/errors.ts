import { z } from 'zod';

/**
 * The two shapes a failed request comes back in.
 *
 * The backend maps its own errors to a body carrying a message and the trace id that ties
 * the response to its server-side log. But request-body validation never reaches those
 * handlers — the web framework answers first, with a list of per-field problems and no
 * trace id. Both arrive as 422, so the status cannot be used to tell them apart, and a
 * client that models only the first shape throws while handling the error rather than
 * reporting it. That is the shape a form produces on almost every wrong keystroke.
 */

/** One field-level problem, as the framework's own validator reports it. */
export const validationIssue = z.object({
  type: z.string(),
  /** Path to the offending field, beginning with where it was found: body, query, path. */
  loc: z.array(z.union([z.string(), z.number()])),
  msg: z.string(),
  input: z.unknown(),
  ctx: z.record(z.string(), z.unknown()).optional(),
});
export type ValidationIssue = z.infer<typeof validationIssue>;

/** An error the application raised deliberately. */
export const domainErrorBody = z.object({
  detail: z.string(),
  trace_id: z.string(),
});

/** An error the framework raised before the application saw the request. */
export const validationErrorBody = z.object({
  detail: z.array(validationIssue),
});

export const errorBody = z.union([domainErrorBody, validationErrorBody]);
export type ErrorBody = z.infer<typeof errorBody>;

/**
 * A field path rendered for a person: the leading `body` or `query` is dropped, since the
 * reader knows which form they are looking at, and what remains is the field they typed in.
 */
export function fieldPath(issue: ValidationIssue): string {
  const [first, ...rest] = issue.loc;
  const parts = first === 'body' || first === 'query' || first === 'path' ? rest : issue.loc;
  return parts.join('.');
}
