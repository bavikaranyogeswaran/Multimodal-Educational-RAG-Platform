import { describe, expect, it } from 'vitest';

import { ConfigurationError, readEnv } from '@/app/env';

const complete = {
  VITE_SUPABASE_URL: 'https://project.supabase.co',
  VITE_SUPABASE_ANON_KEY: 'anon-key',
  VITE_API_BASE_URL: '',
};

describe('reading configuration', () => {
  it('accepts a complete environment', () => {
    expect(readEnv(complete)).toEqual({
      supabaseUrl: 'https://project.supabase.co',
      supabaseAnonKey: 'anon-key',
      apiBaseUrl: '',
    });
  });

  it('treats an absent API base as origin-relative rather than as missing', () => {
    // Empty is the normal case: the development proxy and a single-origin deployment
    // both want requests to stay on this origin.
    const { VITE_API_BASE_URL, ...withoutBase } = complete;
    void VITE_API_BASE_URL;

    expect(readEnv(withoutBase).apiBaseUrl).toBe('');
  });

  it('refuses to start when the sign-in service is not configured', () => {
    const { VITE_SUPABASE_URL, ...withoutUrl } = complete;
    void VITE_SUPABASE_URL;

    expect(() => readEnv(withoutUrl)).toThrow(ConfigurationError);
  });

  it('names every problem at once rather than the first', () => {
    // Fixing one variable, rebuilding, and being told about the next is a slow way to
    // learn there were two.
    const error = (() => {
      try {
        readEnv({ VITE_SUPABASE_URL: 'not-a-url', VITE_SUPABASE_ANON_KEY: '' });
        return null;
      } catch (caught) {
        return caught as Error;
      }
    })();

    expect(error).toBeInstanceOf(ConfigurationError);
    expect(error?.message).toContain('VITE_SUPABASE_URL');
    expect(error?.message).toContain('VITE_SUPABASE_ANON_KEY');
  });
});
