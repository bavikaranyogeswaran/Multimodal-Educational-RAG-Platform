import { z } from 'zod';

/**
 * The field types every response is built out of.
 *
 * Field names throughout these schemas are the backend's own, in snake_case, rather than
 * being renamed to the camelCase this codebase otherwise uses. A contract mirror is worth
 * having only if a drift between the two sides is visible by reading them side by side,
 * and a translation layer hides exactly that: a field the backend renames looks, on this
 * side, like a field somebody forgot to map.
 */

/** An identifier. Stays a string — nothing here does arithmetic on one. */
export const uuid = z.uuid();

/**
 * A point in time, parsed into a Date.
 *
 * The backend emits UTC with a trailing Z and microsecond precision, which the browser
 * truncates to milliseconds — irrelevant for anything shown to a student. Offsets are
 * accepted as well as Z: everything stored is UTC today, but a value that arrived with a
 * real offset would be a correct instant, and rejecting it would turn a timezone change
 * into a parse failure at the client rather than a question at the source.
 */
export const instant = z.iso.datetime({ offset: true }).transform((value) => new Date(value));

/**
 * A calendar date, deliberately left as a string.
 *
 * An exam date is a day in the student's life, not an instant. Passing one through Date
 * would fix it to midnight UTC, which renders as the day before across the Americas, so
 * an exam set for the first of December shows as the thirtieth of November to the person
 * who set it. It is formatted where it is displayed, from these three parts.
 */
export const calendarDate = z.iso.date();
