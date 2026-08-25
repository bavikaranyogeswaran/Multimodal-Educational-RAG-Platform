import { fieldPath, type ValidationIssue } from '@/schemas/errors';

/**
 * Three ways a request fails, kept apart because they call for three different responses.
 *
 * The server refused; the server answered in a shape this client does not recognise; the
 * request never reached a server at all. Collapsing them into one error type would leave
 * every caller to re-derive which happened, and the middle one — the contract having
 * moved underneath us — would be the one that got read as a network blip and retried
 * until it looked like an outage.
 *
 * Fields are declared and assigned rather than written as constructor parameters, because
 * this project compiles with type syntax required to be erasable and a parameter property
 * is the one piece of it that emits code.
 */
export abstract class RequestFailure extends Error {}

/** The server answered, and the answer was a refusal. */
export class ApiError extends RequestFailure {
  override readonly name = 'ApiError';
  readonly status: number;
  /** Ties this response to its server-side log. */
  readonly traceId: string | null;
  /** Per-field problems, when the failure was one. Empty otherwise. */
  readonly issues: readonly ValidationIssue[];

  constructor(
    status: number,
    message: string,
    traceId: string | null,
    issues: readonly ValidationIssue[] = [],
  ) {
    super(message);
    this.status = status;
    this.traceId = traceId;
    this.issues = issues;
  }

  /** Whether asking again could ever produce a different answer. */
  get isRetryable(): boolean {
    return this.status >= 500 || this.status === 429;
  }

  /**
   * Problems keyed by the field that caused them, for putting a message beside an input.
   * A field with more than one problem keeps the first: a single clear sentence under a
   * box is read, and a list of three is not.
   */
  fieldErrors(): Record<string, string> {
    const errors: Record<string, string> = {};
    for (const issue of this.issues) {
      const path = fieldPath(issue);
      if (path && !(path in errors)) {
        errors[path] = issue.msg;
      }
    }
    return errors;
  }
}

/**
 * The server answered successfully, in a shape the schemas do not accept.
 *
 * This is a deployment problem rather than a user problem — the two sides of the contract
 * have moved apart — so it is never retried and never softened into a friendly message.
 * The path and the parse failure are kept because together they name the field that moved.
 */
export class ContractViolationError extends RequestFailure {
  override readonly name = 'ContractViolationError';
  readonly path: string;
  readonly detail: string;

  constructor(path: string, detail: string) {
    super(`The response from ${path} did not match the expected shape: ${detail}`);
    this.path = path;
    this.detail = detail;
  }
}

/** The request never got an answer: offline, DNS, a refused connection, a cancelled fetch. */
export class NetworkError extends RequestFailure {
  override readonly name = 'NetworkError';
  readonly path: string;

  constructor(path: string, cause: unknown) {
    super(`Could not reach the server for ${path}`);
    this.path = path;
    this.cause = cause;
  }
}
