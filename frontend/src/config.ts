export interface AppConfig {
  readonly apiBaseUrl: string;
}

export type ConfigResult =
  | { readonly ok: true; readonly config: AppConfig }
  | { readonly ok: false; readonly message: string };

const MISSING_MESSAGE =
  'VITE_API_BASE_URL is not set. Copy frontend/.env.example to frontend/.env, set it to your ' +
  'backend address (for example http://localhost:8000) and restart npm run dev.';

/** Validate the raw VITE_API_BASE_URL value and normalize it without a trailing slash. */
export function readConfig(raw: unknown): ConfigResult {
  if (typeof raw !== 'string' || raw.trim() === '') {
    return { ok: false, message: MISSING_MESSAGE };
  }
  let url: URL;
  try {
    url = new URL(raw.trim());
  } catch {
    return {
      ok: false,
      message: `VITE_API_BASE_URL is not a valid URL: "${raw}". Use something like http://localhost:8000.`,
    };
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return { ok: false, message: 'VITE_API_BASE_URL must start with http:// or https://.' };
  }
  const path = url.pathname.replace(/\/+$/, '');
  return { ok: true, config: { apiBaseUrl: `${url.origin}${path}` } };
}

export const configResult: ConfigResult = readConfig(import.meta.env.VITE_API_BASE_URL);