/**
 * Utilities for parsing inline citation markers out of assistant message text.
 *
 * Citation markers look like [S1], [S2], etc. The label may use any uppercase letter
 * followed by one or more digits. Splitting on these with a capturing group gives
 * alternating text-and-label segments that components can turn into chip elements.
 */

/** A citation marker pattern: uppercase letter + digits inside square brackets. */
const CITATION_MARKER = /\[([A-Z]\d+)\]/;

/**
 * Split `content` into alternating text and citation-label segments.
 *
 * Even-indexed items are plain text; odd-indexed items are citation labels
 * (the content between the brackets, e.g. "S1"). An empty string at an odd
 * index never appears because the regex always captures a non-empty label.
 *
 * Examples:
 *   "Hello [S1] world [S2]." → ["Hello ", "S1", " world ", "S2", "."]
 *   "No citations here."     → ["No citations here."]
 */
export function parseCitations(content: string): string[] {
  return content.split(CITATION_MARKER);
}
