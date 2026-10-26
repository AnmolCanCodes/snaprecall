const RELATIVE = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
const NUMBER = new Intl.NumberFormat('en');
const DATE = new Intl.DateTimeFormat('en', { dateStyle: 'medium' });
const DATE_TIME = new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' });

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const JUST_NOW_SECONDS = 45;
const RELATIVE_DAYS_LIMIT = 30;

const SNIPPET_OPEN = '[[';
const SNIPPET_CLOSE = ']]';

export interface SnippetPart {
  text: string;
  match: boolean;
}

function unitValue(seconds: number, unit: number): number {
  return Math.sign(seconds) * Math.max(1, Math.floor(Math.abs(seconds) / unit));
}

/** Describe a timestamp relative to now, for example "2 hours ago". */
export function formatRelativeTime(iso: string | null, now: Date = new Date()): string {
  if (!iso) {
    return '';
  }
  const time = Date.parse(iso);
  if (Number.isNaN(time)) {
    return '';
  }
  const seconds = Math.round((time - now.getTime()) / 1000);
  const distance = Math.abs(seconds);
  if (distance < JUST_NOW_SECONDS) {
    return 'just now';
  }
  if (distance < HOUR) {
    return RELATIVE.format(unitValue(seconds, MINUTE), 'minute');
  }
  if (distance < DAY) {
    return RELATIVE.format(unitValue(seconds, HOUR), 'hour');
  }
  if (distance < RELATIVE_DAYS_LIMIT * DAY) {
    return RELATIVE.format(unitValue(seconds, DAY), 'day');
  }
  return DATE.format(time);
}

/** Absolute date and time such as "Oct 25, 2026, 10:00 AM". */
export function formatDateTime(iso: string | null): string {
  if (!iso) {
    return '';
  }
  const time = Date.parse(iso);
  return Number.isNaN(time) ? '' : DATE_TIME.format(time);
}

export function formatNumber(value: number): string {
  return NUMBER.format(value);
}

export function formatDimensions(width: number | null, height: number | null): string | null {
  return width !== null && height !== null ? `${formatNumber(width)} x ${formatNumber(height)}` : null;
}

export function formatBytes(bytes: number | null): string | null {
  if (bytes === null) {
    return null;
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(0)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Split a backend snippet into plain and highlighted parts. Highlights are wrapped in
 * [[ and ]]. Unbalanced markers are left as plain text.
 */
export function parseSnippet(snippet: string): SnippetPart[] {
  const parts: SnippetPart[] = [];
  let cursor = 0;
  while (cursor < snippet.length) {
    const open = snippet.indexOf(SNIPPET_OPEN, cursor);
    if (open === -1) {
      break;
    }
    const close = snippet.indexOf(SNIPPET_CLOSE, open + SNIPPET_OPEN.length);
    if (close === -1) {
      break;
    }
    if (open > cursor) {
      parts.push({ text: snippet.slice(cursor, open), match: false });
    }
    const matched = snippet.slice(open + SNIPPET_OPEN.length, close);
    if (matched !== '') {
      parts.push({ text: matched, match: true });
    }
    cursor = close + SNIPPET_CLOSE.length;
  }
  if (cursor < snippet.length) {
    parts.push({ text: snippet.slice(cursor), match: false });
  }
  return parts;
}

/** Copy text to the clipboard. Returns false when the browser refuses. */
export async function copyText(text: string): Promise<boolean> {
  if (typeof navigator === 'undefined' || !navigator.clipboard) {
    return false;
  }
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}