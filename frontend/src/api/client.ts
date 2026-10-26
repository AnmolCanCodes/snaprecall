import { configResult } from '../config';
import type { HealthResponse, ImageDetail, IndexStatus, ScanResult, SearchResponse } from './types';

export type ApiErrorKind = 'network' | 'http' | 'parse';

export const NETWORK_MESSAGE = 'Cannot reach the SnapRecall backend. Is it running?';
const PARSE_MESSAGE = 'The backend sent a response SnapRecall could not read.';

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;

  constructor(kind: ApiErrorKind, message: string, status: number | null = null) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
  }
}

/** True when a rejection came from an AbortController, which callers should ignore. */
export function isAbortError(error: unknown): boolean {
  return typeof error === 'object' && error !== null && 'name' in error && error.name === 'AbortError';
}

/** Turn any thrown value into a short message that is safe to show in the UI. */
export function describeError(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.';
}

function baseUrl(): string {
  if (!configResult.ok) {
    throw new Error(configResult.message);
  }
  return configResult.config.apiBaseUrl;
}

async function readErrorDetail(response: Response): Promise<string> {
  const fallback = `The backend returned an error (HTTP ${response.status}).`;
  try {
    const body: unknown = await response.json();
    if (
      typeof body === 'object' &&
      body !== null &&
      'detail' in body &&
      typeof body.detail === 'string' &&
      body.detail !== ''
    ) {
      return body.detail;
    }
  } catch {
    return fallback;
  }
  return fallback;
}

async function send(path: string, init: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl()}${path}`, init);
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new ApiError('network', NETWORK_MESSAGE);
  }
  if (!response.ok) {
    throw new ApiError('http', await readErrorDetail(response), response.status);
  }
  return response;
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await send(path, init);
  try {
    const data: unknown = await response.json();
    return data as T;
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new ApiError('parse', PARSE_MESSAGE, response.status);
  }
}

export function search(
  query: string,
  limit: number | undefined,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query });
  if (limit !== undefined) {
    params.set('limit', String(limit));
  }
  return requestJson<SearchResponse>(`/api/search?${params.toString()}`, { signal });
}

export function getImage(id: number, signal?: AbortSignal): Promise<ImageDetail> {
  return requestJson<ImageDetail>(`/api/images/${id}`, { signal });
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return requestJson<HealthResponse>('/api/health', { signal });
}

export function getIndexStatus(signal?: AbortSignal): Promise<IndexStatus> {
  return requestJson<IndexStatus>('/api/index/status', { signal });
}

export function startScan(signal?: AbortSignal): Promise<ScanResult> {
  return requestJson<ScanResult>('/api/index/scan', { method: 'POST', signal });
}

export function pauseIndexing(signal?: AbortSignal): Promise<IndexStatus> {
  return requestJson<IndexStatus>('/api/index/pause', { method: 'POST', signal });
}

export function resumeIndexing(signal?: AbortSignal): Promise<IndexStatus> {
  return requestJson<IndexStatus>('/api/index/resume', { method: 'POST', signal });
}

/** URL for use as an <img src>. Never fetched as JSON. */
export function thumbnailUrl(id: number): string {
  return `${baseUrl()}/api/images/${id}/thumbnail`;
}

/** URL of the original file, for <img src> and links. */
export function fileUrl(id: number): string {
  return `${baseUrl()}/api/images/${id}/file`;
}

/** Download the original file as a Blob so it can be saved across origins. */
export async function fetchFileBlob(id: number, signal?: AbortSignal): Promise<Blob> {
  const response = await send(`/api/images/${id}/file`, { signal });
  return response.blob();
}