import { describe, expect, it } from 'vitest';

import { parseCitations } from '@/features/conversations/citationUtils';

describe('parseCitations', () => {
  it('returns a single segment when there are no citation markers', () => {
    expect(parseCitations('No citations here.')).toEqual(['No citations here.']);
  });

  it('splits a single marker into three segments', () => {
    // Even = text, odd = label, even = text.
    expect(parseCitations('See [S1] for details.')).toEqual([
      'See ',
      'S1',
      ' for details.',
    ]);
  });

  it('handles multiple markers', () => {
    expect(parseCitations('Hello [S1] world [S2].')).toEqual([
      'Hello ',
      'S1',
      ' world ',
      'S2',
      '.',
    ]);
  });

  it('handles a marker at the start', () => {
    expect(parseCitations('[S1] starts the sentence.')).toEqual([
      '',
      'S1',
      ' starts the sentence.',
    ]);
  });

  it('handles a marker at the end', () => {
    expect(parseCitations('The answer is here [S3]')).toEqual([
      'The answer is here ',
      'S3',
      '',
    ]);
  });

  it('does not match lowercase letters (markers must start with an uppercase letter)', () => {
    expect(parseCitations('Not a marker [s1].')).toEqual(['Not a marker [s1].']);
  });

  it('does not match markers without digits', () => {
    expect(parseCitations('Not [S] either.')).toEqual(['Not [S] either.']);
  });

  it('handles multi-digit labels like [S12]', () => {
    expect(parseCitations('Two digits [S12] here.')).toEqual([
      'Two digits ',
      'S12',
      ' here.',
    ]);
  });

  it('returns a single empty string for empty input', () => {
    expect(parseCitations('')).toEqual(['']);
  });
});
