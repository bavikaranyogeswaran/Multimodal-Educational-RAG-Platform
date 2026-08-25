import { z } from 'zod';

/**
 * The configuration this application needs to start, checked once.
 *
 * Read through a schema rather than off `import.meta.env` at each use, and read at
 * startup rather than at the moment a value is first needed. A missing sign-in URL that
 * surfaces where it is used produces a failure inside the authentication library, several
 * layers from the cause, on the first person who tries to sign in. Checked here it is a
 * sentence naming the variable, before anything renders.
 */

const environment = z.object({
  VITE_SUPABASE_URL: z.url({ error: 'must be the URL of your Supabase project' }),
  VITE_SUPABASE_ANON_KEY: z
    .string()
    .min(1, { error: 'must be your project’s anon key, which is safe to publish' }),
  /**
   * Where the API lives. Empty is the normal case and not a missing value: requests then
   * stay origin-relative and the development server proxies them, which is also how a
   * single-origin deployment serves them.
   */
  VITE_API_BASE_URL: z.string().default(''),
});

export interface AppEnv {
  supabaseUrl: string;
  supabaseAnonKey: string;
  apiBaseUrl: string;
}

/** Thrown at startup, naming every variable that is wrong rather than only the first. */
export class ConfigurationError extends Error {
  override readonly name = 'ConfigurationError';

  constructor(problems: readonly string[]) {
    super(
      `The application is not configured correctly:\n${problems.map((p) => `  - ${p}`).join('\n')}`,
    );
  }
}

export function readEnv(source: Partial<ImportMetaEnv> = import.meta.env): AppEnv {
  const parsed = environment.safeParse(source);
  if (!parsed.success) {
    throw new ConfigurationError(
      parsed.error.issues.map((issue) => `${issue.path.join('.')} ${issue.message}`),
    );
  }
  return {
    supabaseUrl: parsed.data.VITE_SUPABASE_URL,
    supabaseAnonKey: parsed.data.VITE_SUPABASE_ANON_KEY,
    apiBaseUrl: parsed.data.VITE_API_BASE_URL,
  };
}
