/// <reference types="vite/client" />

/**
 * The environment this application is built with.
 *
 * Declared rather than left to the framework's catch-all index signature, which types
 * every variable as `any` and so lets a misspelt name through as a value that is simply
 * undefined at runtime.
 */
interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL: string;
  readonly VITE_SUPABASE_ANON_KEY: string;
  /** Empty in development, where requests stay origin-relative and the dev server proxies. */
  readonly VITE_API_BASE_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
