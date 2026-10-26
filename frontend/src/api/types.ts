export type ImageStatus = 'pending' | 'processing' | 'done' | 'failed';
export type MatchLeg = 'keyword' | 'semantic';
export type ProviderName = 'gemini' | 'ollama';
export type PausedReason = 'quota_exhausted' | 'daily_budget';

export interface ImageBase {
  id: number;
  filename: string;
  width: number | null;
  height: number | null;
  size_bytes: number | null;
  status: ImageStatus;
  summary: string;
  tags: string[];
  app_type: string;
  visible_text: string;
  created_at: string;
  indexed_at: string | null;
}

export interface ImageDetail extends ImageBase {
  ocr_text: string;
  attempts: number;
  error: string | null;
}

export interface SearchHit {
  image: ImageBase;
  score: number;
  matched_by: MatchLeg[];
  snippet: string | null;
}

export interface SearchResponse {
  query: string;
  total: number;
  degraded: boolean;
  results: SearchHit[];
}

export interface ComponentCheck {
  ok: boolean;
  detail: string | null;
}

/**
 * Fields marked optional were added by the provider refactor and are not yet confirmed
 * against backend/app/schemas.py.
 */
export interface HealthResponse {
  status: 'ok' | 'degraded';
  database: ComponentCheck;
  vision_model: ComponentCheck;
  embedding_model: ComponentCheck;
  tesseract: ComponentCheck;
  screenshot_dir: ComponentCheck;
  provider_name?: ProviderName;
  provider?: ComponentCheck;
  api_key_configured?: boolean;
  embedding_mismatch?: boolean;
  requests_today?: number;
  paused_reason?: PausedReason | null;
}

export interface IndexStatus {
  pending: number;
  processing: number;
  done: number;
  failed: number;
  total: number;
  current_filename: string | null;
  paused: boolean;
  provider_ok: boolean;
  paused_reason: PausedReason | null;
  requests_today: number;
}

export interface ScanResult {
  added: number;
  requeued: number;
  removed: number;
  unchanged: number;
}