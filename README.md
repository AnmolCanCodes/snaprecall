# SnapRecall

**Find any screenshot by typing what you remember about it.**

SnapRecall watches your screenshots folder, lets an AI model read every image in the background, and builds a searchable index. Instead of scrolling through thousands of files named `screenshot_2026-10-24-14-55-16.png`, you type "rahul payment 2500" or "docker permission error" and the matching screenshots appear.

<div align="center">
  <img src="SnapRecall Screenshot Search Hero.png" alt="SnapRecall — AI-powered screenshot search" width="100%" />

  <p><strong>Find any screenshot by typing what you remember about it.</strong></p>

  <p>AI-powered screenshot indexing · Hybrid search · English, Hindi & Hinglish</p>
</div>

Built for the Hacktoberfest DEV Challenge, Week 3 (theme: "Slow and Steady").

---

## Table of contents

- [The problem](#the-problem)
- [What SnapRecall does](#what-snaprecall-does)
- [Features](#features)
- [How it works](#how-it-works)
  - [Architecture overview](#architecture-overview)
  - [1. Discovery and folder watching](#1-discovery-and-folder-watching)
  - [2. Queue and resilient background worker](#2-queue-and-resilient-background-worker)
  - [3. Indexing pipeline](#3-indexing-pipeline)
  - [4. Hybrid search engine](#4-hybrid-search-engine)
- [Hosted mode vs local mode](#hosted-mode-vs-local-mode)
  - [Feature comparison](#feature-comparison)
  - [Hosted mode (Gemini API)](#hosted-mode-gemini-api)
  - [Local mode (Ollama)](#local-mode-ollama)
- [Tech stack](#tech-stack)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [API overview](#api-overview)
- [Project structure](#project-structure)
- [Privacy and security](#privacy-and-security)
- [Why open-weight AI](#why-open-weight-ai)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## The problem

Screenshots are the fastest way to save something: a payment confirmation, a chat, an error message, a ticket. They are also the hardest thing to find later. Every file has a timestamp for a name, the folder grows into the thousands, and the only way to search it is to scroll through thumbnails and squint.

## What SnapRecall does

1. **Watches** your screenshot folder for new or modified images.
2. **Understands** each image with a vision model, producing a concise summary, tags, screenshot category, and visible text (in English, Hindi, and Hinglish).
3. **Indexes** the extracted content into a local SQLite database using both full-text keyword search (FTS5) and semantic vector search (`sqlite-vec`).
4. **Retrieves** matching screenshots through hybrid rank fusion when you search in natural language.

Your original files are never renamed, moved, or modified.

## Features

- **Background indexing:** New screenshots are detected and queued automatically as you take them.
- **Slow and steady backfill:** Existing backlogs are processed one-by-one with configurable pauses, keeping system resources and API limits under control.
- **Zero-cost deduplication:** Images identical by SHA-256 reuse existing metadata and vectors instantly without redundant model inference.
- **Rate-limit and budget aware:** Automatically backs off on API 429 errors, respects daily request quotas, and auto-resumes at local midnight.
- **Multilingual understanding:** Understands screenshots containing English, Devanagari Hindi, and mixed Hinglish.
- **Hybrid search (BM25 + Vector KNN):** Combines exact keyword matching with semantic concept search via Reciprocal Rank Fusion (RRF).
- **Graceful degradation:** If embedding services are offline, search seamlessly falls back to keyword-only mode.
- **Dual provider flexibility:** Run hosted with Google Gemini API (light on hardware) or 100% locally with Ollama (completely private and offline).
- **Modern web UI:** Fast React interface with live indexing progress, thumbnail preview grids, full-detail inspection modals, and direct file access.

---

## How it works

### Architecture overview

```
 +---------------------------------------------------------------------------------------+
 |                                  INGESTION LAYER                                      |
 |                                                                                       |
 |  Screenshots Folder (SCREENSHOT_DIR)                                                  |
 |         │                                                                             |
 |         ├─► [Startup Backfill Scanner] ── (scandir walk, skips temp/ignored files) ──┐ |
 |         │                                                                            ▼ |
 |         └─► [Live Watcher (Watchdog)] ── (write stability check, move/delete sync) ─►│ |
 +--------------------------------------------------------------------------------------│+
                                                                                        │
                                                                                        ▼
 +---------------------------------------------------------------------------------------+
 |                             QUEUE & BACKGROUND WORKER                                 |
 |                                                                                       |
 |  SQLite `images` Table (status: pending ──► processing ──► done / failed)             |
 |         │                                                                             |
 |         │  • Claims newest first (ORDER BY mtime DESC, id DESC)                       |
 |         │  • Throttles between images (WORKER_THROTTLE_SECONDS)                       |
 |         │  • Daily budget tracking & auto-resume at midnight                          |
 |         │  • Exponential backoff on 429 rate limits & retry-after parsing             |
 |         ▼                                                                             |
 +---------------------------------------------------------------------------------------+
                                           │
                                           ▼
 +---------------------------------------------------------------------------------------+
 |                                 INDEXING PIPELINE                                     |
 |                                                                                       |
 |  1. Checksum & Deduplication:                                                         |
 |     Computes SHA-256. If file hash already indexed, copies vector & metadata instantly |
 |     (skips LLM & embedding calls completely — zero cost & instant!).                 |
 |                                                                                       |
 |  2. Image Preprocessing:                                                              |
 |     Reads dimensions, downscales longest side to MAX_IMAGE_SIDE (default 1024px),      |
 |     generates base64 payload.                                                         |
 |                                                                                       |
 |  3. Parallel Extraction:                                                              |
 |     ┌────────────────────────────────────┐    ┌────────────────────────────────────┐  |
 |     │ Vision Analysis (Gemini or Ollama) │    │ Optional OCR (Tesseract eng+hin)   │  |
 |     │ Structured JSON output:            │    │ Extracted verbatim text strings    │  |
 |     │ - summary (concise overview)       │    │ (enabled if OCR_ENGINE=tesseract)  │  |
 |     │ - tags (3-8 categorical tags)      │    │                                    │  |
 |     │ - app_type (chat, payment, code...)│    │                                    │  |
 |     │ - visible_text (Hindi / Hinglish / │    │                                    │  |
 |     │   English verbatim text)           │    │                                    │  |
 |     └─────────────────┬──────────────────┘    └─────────────────┬──────────────────┘  |
 |                       └─────────────────┬───────────────────────┘                     |
 |                                         ▼                                             |
 |  4. Document Text Assembly & Embeddings:                                              |
 |     Combines summary + type + tags + visible text + OCR into unified document text.   |
 |     Generates dense embedding vector (EMBEDDING_DIM = 768).                           |
 |                                                                                       |
 |  5. Storage & Triggers:                                                               |
 |     - Updates `images` table with metadata & status='done'.                           |
 |     - SQLite trigger updates `images_fts` (FTS5 BM25 index with unicode61).           |
 |     - Inserts vector into `vec_images` (sqlite-vec KNN virtual table).                |
 |     - Generates lightweight WebP thumbnail in `data/thumbnails/{id}.webp`.            |
 +---------------------------------------------------------------------------------------+
                                           ▲
                                           │
 +---------------------------------------------------------------------------------------+
 |                              HYBRID SEARCH & RETRIEVAL                                |
 |                                                                                       |
 |  User Query (Search Box) ────────────────────────────────────────────────────────┐    |
 |         │                                                                        │    |
 |         ▼                                                                        ▼    |
 |  [Keyword Search Leg]                                                   [Semantic Leg]|
 |  - Sanitizes query (safe tokens & Devanagari)               - Embeds query with task  |
 |  - BM25 matching via SQLite FTS5                            - KNN vector search via   |
 |  - Extracts highlighted snippets                              sqlite-vec              |
 |         │                                                                        │    |
 |         └───────────────────────────────┬────────────────────────────────────────┘    |
 |                                         ▼                                             |
 |                      [Reciprocal Rank Fusion (RRF_K=60)]                              |
 |                      Fuses ranks: score = Σ (1 / (60 + rank))                         |
 |                      Graceful fallback: degrades to keyword-only if provider offline  |
 |                                         │                                             |
 |                                         ▼                                             |
 |                            FastAPI REST API (/api/search)                             |
 |                                         │                                             |
 |                                         ▼                                             |
 |                   React 18 Frontend (Search, Previews, Progress Bar)                  |
 +---------------------------------------------------------------------------------------+
```

### 1. Discovery and folder watching

- **Startup reconciliation (`scan_folder`):** On startup (when `BACKFILL_ON_START=true`), SnapRecall walks `SCREENSHOT_DIR` using `os.scandir`. It skips hidden files (`.*`), temporary downloads (`.tmp`, `.part`, `.crdownload`), and unsupported extensions. New files are inserted into SQLite as `pending`, modified files (detected via `mtime` and `size_bytes`) are requeued, and deleted files have their records and thumbnails cleaned up.
- **Live filesystem watcher (`FolderWatcher`):** Uses `watchdog` to monitor the folder in real time. Before queuing a newly created file, it performs stability checks (`_wait_until_stable`), polling file size across intervals to ensure the operating system has finished writing the screenshot to disk. File renames and moves update the path in SQLite directly without re-indexing.

### 2. Queue and resilient background worker

- **SQLite-backed job queue:** Jobs reside in the `images` table with states: `pending` → `processing` → `done` (or `failed`).
- **Newest-first priority:** The worker claims the newest images first (`ORDER BY mtime DESC, id DESC`), ensuring that screenshots you just took become searchable right away.
- **Throttling & budget controls:** The worker pauses for `WORKER_THROTTLE_SECONDS` between images. If `DAILY_REQUEST_BUDGET` is set and reached, or if the provider reports quota exhaustion, the worker automatically pauses and a background timer auto-resumes processing at local midnight.
- **Rate-limit resilience:** HTTP 429 errors parse `Retry-After` headers and apply exponential backoff without counting toward failure retry limits. Images are only marked as `failed` after exhausting `WORKER_MAX_RETRIES` non-rate-limit errors.

### 3. Indexing pipeline

For each queued screenshot:
1. **Deduplication:** Computes the SHA-256 hash. If an identical file has already been indexed, metadata and vector embeddings are copied directly using `copy_vector`. No LLM or embedding API calls are made.
2. **Preprocessing:** Image dimensions are recorded, and the image is downscaled so its longest side does not exceed `MAX_IMAGE_SIDE` (default 1024px), reducing bandwidth and token usage.
3. **Multimodal analysis:** The image base64 is sent to the vision model with a structured JSON prompt instructing it to extract:
   - `summary`: A concise 1-2 sentence description.
   - `tags`: 3 to 8 lowercase categorical keywords.
   - `app_type`: Categorized into one of 13 types (`chat`, `payment`, `code`, `error`, `document`, `social`, `shopping`, `map`, `ticket`, `email`, `settings`, `web`, `other`).
   - `visible_text`: All readable text, preserving names, amounts, numbers, error codes, and Hindi (Devanagari) / Hinglish verbatim.
4. **Optional OCR:** If `OCR_ENGINE=tesseract`, Tesseract OCR runs in parallel (`eng+hin`). If `OCR_ENGINE=none`, the vision model handles text extraction directly.
5. **Embedding generation:** Searchable fields (`Summary`, `Type`, `Tags`, `Visible text`, `OCR text`) are merged into a unified document representation and passed to the embedding model (`EMBEDDING_DIM=768`) under the `document` task type.
6. **Persistence:** Metadata is saved in the `images` table. SQLite database triggers automatically update the `images_fts` FTS5 table, the vector is stored in `vec_images` via `sqlite-vec`, and a lightweight WebP thumbnail is cached in `data/thumbnails/`.

### 4. Hybrid search engine

SnapRecall performs both keyword and semantic searches in parallel and fuses the results:
- **Keyword leg (BM25 via FTS5):** User queries are sanitized (`sanitize_fts_query`) into safe prefix tokens (preserving alphanumeric characters and Devanagari combining marks) and matched against the FTS5 full-text index with BM25 scoring and contextual snippet highlighting.
- **Semantic leg (KNN via sqlite-vec):** The query is embedded under the `query` task type and matched against indexed vectors using cosine distance in `sqlite-vec`.
- **Reciprocal Rank Fusion (RRF):** Merges the top candidates from both lists using:
  $$\text{RRF Score} = \sum_{m \in \{\text{keyword}, \text{semantic}\}} \frac{1}{k + \text{rank}_m} \quad (k = 60)$$
  Exact numbers, codes, and names are captured by the keyword leg, while vague conceptual queries are captured by the semantic leg.
- **Graceful degradation:** If the embedding model or network is unavailable, semantic search fails safely and the engine returns keyword results with a `degraded: true` indicator.

---

## Hosted mode vs local mode

SnapRecall supports two distinct backends through the `LLM_PROVIDER` setting. The database schema, hybrid search pipeline, and web UI remain identical in both modes.

### Feature comparison

| Feature | Hosted Mode (`gemini`) | Local Mode (`ollama`) |
|---|---|---|
| **Primary provider** | Google Gemini API | Local Ollama server |
| **Vision model (`VISION_MODEL`)** | `gemini-3-flash-preview` (or `gemini-1.5-flash`) | `gemma3:4b` (or `gemma3:12b`, `llava`) |
| **Embedding model (`EMBEDDING_MODEL`)** | `gemini-embedding-001` (or `text-embedding-004`) | `embeddinggemma` |
| **Embedding dimensions (`EMBEDDING_DIM`)** | `768` | `768` |
| **Hardware requirements** | Any lightweight laptop or desktop | GPU or fast CPU with 8GB+ RAM |
| **Data privacy** | Images sent to Google API over HTTPS | 100% on-device; no data leaves your machine |
| **Offline support** | Requires internet access | Works completely offline |
| **Cost** | Google AI Studio free tier / pay-as-you-go | Completely free (electricity only) |
| **Rate limits** | Subject to API request quotas (handled by worker) | No rate limits |

### Hosted mode (Gemini API)

Hosted mode is the recommended choice for fast setup and low hardware requirements.

1. Obtain a free API key from [Google AI Studio](https://aistudio.google.com/apikey).
2. Configure `.env`:
   ```env
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=your_gemini_api_key_here
   VISION_MODEL=gemini-3-flash-preview
   EMBEDDING_MODEL=gemini-embedding-001
   EMBEDDING_DIM=768
   ```

### Local mode (Ollama)

Local mode is ideal for privacy-conscious users who do not want screenshot data to leave their machine.

1. Install and start [Ollama](https://ollama.com).
2. Pull the required vision and embedding models:
   ```bash
   ollama pull gemma3:4b
   ollama pull embeddinggemma
   ```
3. Configure `.env`:
   ```env
   LLM_PROVIDER=ollama
   OLLAMA_BASE_URL=http://localhost:11434
   VISION_MODEL=gemma3:4b
   EMBEDDING_MODEL=embeddinggemma
   EMBEDDING_DIM=768
   ```

---

## Tech stack

| Layer | Technology | Purpose |
|---|---|---|
| **Backend Framework** | FastAPI (Python 3.11+) | Async REST API, lifecycle management, CORS |
| **Database & Search** | SQLite3 + FTS5 + `sqlite-vec` | Relational metadata, BM25 full-text search, vector KNN search |
| **Vision & Embeddings** | Google Gemini API / Ollama | Multimodal screenshot description, 768-dim vector embeddings |
| **Filesystem Watcher** | `watchdog` | Real-time screenshot folder change monitoring |
| **Image Processing** | Pillow (PIL) | Thumbnail generation, dimension checks, downscaling |
| **OCR (Optional)** | Tesseract OCR (`pytesseract`) | English and Hindi optical character recognition |
| **Frontend Framework** | React 18 + TypeScript + Vite | Responsive web UI, instant search, indexing status |
| **Styling** | Custom CSS Variables & Tokens | Dark/light themed modern layout without framework bloat |

---

## Getting started

### Prerequisites

- **Python:** Version 3.11 or newer (ensure SQLite extension loading is enabled).
- **Node.js:** Version 20 or newer.
- **Model backend:** Either a [Google AI Studio API key](https://aistudio.google.com/apikey) (hosted) or [Ollama](https://ollama.com) installed and running (local).
- **Optional OCR:** Tesseract OCR (only needed if setting `OCR_ENGINE=tesseract`):
  - Ubuntu/Debian: `sudo apt install tesseract-ocr tesseract-ocr-hin`
  - macOS: `brew install tesseract tesseract-lang`
  - Windows: UB Mannheim installer, then set `TESSERACT_CMD` in `.env`

### 1. Clone and configure

```bash
git clone https://github.com/AnmolCanCodes/snaprecall.git
cd snaprecall
cp .env.example .env
```

Open `.env` in an editor and set your configuration:
- Set `SCREENSHOT_DIR` to the folder where your screenshots are stored.
- For **Hosted mode**: Ensure `LLM_PROVIDER=gemini` and set `GEMINI_API_KEY`.
- For **Local mode**: Set `LLM_PROVIDER=ollama`, `VISION_MODEL=gemma3:4b`, and `EMBEDDING_MODEL=embeddinggemma`.

### 2. Run the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Verify backend health at: http://localhost:8000/api/health  
Interactive Swagger docs: http://localhost:8000/docs

### 3. Run the frontend

```bash
cd frontend
cp .env.example .env            # Sets VITE_API_BASE_URL=http://localhost:8000
npm install
npm run dev
```

Open http://localhost:5173 in your browser. The indexing progress bar will reflect background progress in real time.

---

## Configuration

All configuration is managed through environment variables in the root `.env` file. Below is the complete reference matching `.env.example`:

### API settings

| Variable | Description | Default |
|---|---|---|
| `APP_ENV` | Application environment (`development`, `production`) | `development` |
| `API_HOST` | Host interface for FastAPI to bind | `127.0.0.1` |
| `API_PORT` | Port for FastAPI backend | `8000` |
| `LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `CORS_ORIGINS` | Comma-separated list of allowed web origins | `http://localhost:5173` |

### Screenshots and watching

| Variable | Description | Default |
|---|---|---|
| `SCREENSHOT_DIR` | Absolute path to folder containing screenshots (**Required**) | _Empty_ |
| `SCAN_RECURSIVE` | Whether to scan subdirectories inside `SCREENSHOT_DIR` | `false` |
| `WATCH_ENABLED` | Enable live filesystem monitoring via watchdog | `true` |
| `BACKFILL_ON_START` | Automatically index existing screenshots upon startup | `true` |
| `SUPPORTED_EXTENSIONS`| Comma-separated list of indexed image file extensions | `png,jpg,jpeg,webp` |

### Storage and thumbnails

| Variable | Description | Default |
|---|---|---|
| `DATA_DIR` | Directory where `snaprecall.db` and thumbnails are stored | `./data` |
| `THUMBNAIL_SIZE` | Max width/height in pixels for cached thumbnails | `360` |

### Model provider

| Variable | Description | Default |
|---|---|---|
| `LLM_PROVIDER` | Active model provider: `gemini` or `ollama` | `gemini` |

### Gemini API (`LLM_PROVIDER=gemini`)

| Variable | Description | Default |
|---|---|---|
| `GEMINI_API_KEY` | Google AI Studio API key | _Empty_ |
| `GEMINI_BASE_URL` | Base URL for Google Generative Language REST API | `https://generativelanguage.googleapis.com/v1beta` |
| `REQUEST_TIMEOUT_SECONDS` | Timeout in seconds for HTTP requests to Gemini | `120` |

### Ollama (`LLM_PROVIDER=ollama`)

| Variable | Description | Default |
|---|---|---|
| `OLLAMA_BASE_URL` | Base URL of your local running Ollama instance | `http://localhost:11434` |

### Models and dimensions

| Variable | Description | Default |
|---|---|---|
| `VISION_MODEL` | Model ID used to read and describe screenshots | `gemini-3-flash-preview` |
| `EMBEDDING_MODEL` | Model ID used to generate vector embeddings | `gemini-embedding-001` |
| `EMBEDDING_DIM` | Vector dimension size produced by `EMBEDDING_MODEL` | `768` |
| `MAX_IMAGE_SIDE` | Max dimension (px) sent to the vision model | `1024` |

> [!IMPORTANT]
> If you change `EMBEDDING_MODEL` or `EMBEDDING_DIM`, you must delete `data/snaprecall.db` and re-index. Vectors from different models or dimensions cannot be compared, and the backend halts indexing if a mismatch is detected.

### OCR

| Variable | Description | Default |
|---|---|---|
| `OCR_ENGINE` | OCR mode: `none` (recommended in hosted mode) or `tesseract` | `none` |
| `OCR_LANGS` | Tesseract language codes separated by `+` | `eng+hin` |
| `TESSERACT_CMD` | Explicit path to Tesseract binary (if not in PATH) | _Empty_ |

### Background worker

| Variable | Description | Default |
|---|---|---|
| `WORKER_THROTTLE_SECONDS` | Pause in seconds between indexing consecutive images | `6` |
| `WORKER_MAX_RETRIES` | Max non-rate-limit error attempts before marking failed | `3` |
| `DAILY_REQUEST_BUDGET` | Max API requests permitted per day (`0` = unlimited) | `0` |

### Search

| Variable | Description | Default |
|---|---|---|
| `SEARCH_DEFAULT_LIMIT` | Default number of search results returned | `24` |
| `SEARCH_CANDIDATES` | Candidates retrieved per leg before rank fusion | `50` |
| `RRF_K` | Reciprocal Rank Fusion smoothing parameter | `60` |

---

## API overview

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Comprehensive system health check (DB, provider, models, quotas) |
| `GET` | `/api/search?q={query}&limit={n}` | Hybrid keyword + semantic search (empty query returns recent files) |
| `GET` | `/api/images/{id}` | Full metadata, tags, summary, and text for a screenshot |
| `GET` | `/api/images/{id}/thumbnail` | Cached WebP thumbnail image |
| `GET` | `/api/images/{id}/file` | Original screenshot file (restricted to `SCREENSHOT_DIR`) |
| `GET` | `/api/index/status` | Queue counts (`pending`, `processing`, `done`, `failed`) and state |
| `POST`| `/api/index/scan` | Trigger a manual folder scan and wake worker |
| `POST`| `/api/index/pause` | Pause background indexing worker |
| `POST`| `/api/index/resume` | Resume background indexing worker |

---

## Project structure

```
snaprecall/
├── backend/
│   ├── app/
│   │   ├── api/                 # API route endpoints
│   │   │   ├── health.py        # /api/health diagnostics
│   │   │   ├── images.py        # /api/images/{id} metadata, thumbnail, file
│   │   │   ├── index.py         # /api/index queue controls and status
│   │   │   └── search.py        # /api/search hybrid search endpoint
│   │   ├── services/            # Core business logic
│   │   │   ├── embeddings.py    # Document text builder & vector embedding
│   │   │   ├── gemini_client.py # Async HTTP client for Gemini API
│   │   │   ├── llm_client.py    # Abstract LLM client interface & tracker
│   │   │   ├── ocr.py           # Tesseract OCR extraction
│   │   │   ├── ollama_client.py # Async HTTP client for Ollama API
│   │   │   ├── pipeline.py      # Single screenshot indexing pipeline
│   │   │   ├── search.py        # FTS5 + sqlite-vec + Reciprocal Rank Fusion
│   │   │   ├── vision.py        # Multimodal vision prompt & JSON parser
│   │   │   ├── watcher.py       # Watchdog filesystem monitor & folder scan
│   │   │   └── worker.py        # Resilient, throttled background queue worker
│   │   ├── utils/               # Helpers (hashing, images, logging)
│   │   ├── config.py            # Typed Pydantic settings from root .env
│   │   ├── db.py                # SQLite schema, FTS5 triggers, sqlite-vec
│   │   ├── main.py              # FastAPI application lifecycle
│   │   └── schemas.py           # Pydantic request and response schemas
│   ├── tests/                   # Pytest test suite (75+ unit & integration tests)
│   ├── pyproject.toml
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/                 # Typed backend API client
│   │   ├── components/          # SearchBar, ResultGrid, ImageModal, IndexStatus
│   │   ├── hooks/               # Custom hooks for search and queue status polling
│   │   ├── styles/              # Design system and theme tokens
│   │   └── App.tsx              # Main dashboard view
│   ├── package.json
│   └── vite.config.ts
├── data/                        # SQLite DB and thumbnails (git-ignored)
├── .env.example                 # Documented environment template
└── README.md
```

---

## Privacy and security

- **Local mode guarantees:** When `LLM_PROVIDER=ollama`, all vision and embedding processing happens locally on your machine. No screenshot data, text, or vectors leave your computer.
- **Hosted mode awareness:** When `LLM_PROVIDER=gemini`, downscaled screenshots and search queries are transmitted to Google's API over HTTPS. Be aware of your provider's terms of service regarding sensitive data.
- **Localhost binding:** The backend binds to `127.0.0.1` by default, preventing unintended network exposure.
- **Directory traversal prevention:** The `/api/images/{id}/file` endpoint resolves files strictly via database primary keys and ensures the resolved path is contained within `SCREENSHOT_DIR`.
- **Safe data isolation:** The SQLite database and generated thumbnails reside in `data/`, which is ignored by version control.
- **Credential safety:** API keys are loaded exclusively from `.env` and are never logged, returned in API responses, or exposed to the frontend.

---

## Why open-weight AI

SnapRecall is designed around the open-weight philosophy:
- **Deployment freedom:** The architecture works identically whether connected to hosted APIs or run entirely locally via open-weight models like Gemma.
- **Long-term preservation:** Unlike proprietary cloud services that can deprecate models or shut down APIs, open-weight models remain functional offline indefinitely.
- **Predictable economics:** Local processing has zero marginal cost per image, enabling you to index tens of thousands of screenshots without subscription fees.
- **True privacy:** Screenshots frequently contain OTPs, bank statements, personal chats, and proprietary code. Open-weight models empower you to keep sensitive personal data completely confidential.

---

## Troubleshooting

| Problem | Cause and Solution |
|---|---|
| **`/api/health` reports API key missing** | `GEMINI_API_KEY` is empty in `.env`. Add your Google AI Studio key and restart the backend. |
| **No screenshots are being indexed** | Ensure `SCREENSHOT_DIR` points to an existing directory containing supported images (`png,jpg,jpeg,webp`). Check `/api/index/status` to see if the worker is paused. |
| **Indexing pauses automatically** | The daily request limit (`DAILY_REQUEST_BUDGET`) or API quota was reached. The worker auto-resumes at local midnight, or you can resume manually via the UI. |
| **`embedding_mismatch` reported in health check** | You modified `EMBEDDING_MODEL` or `EMBEDDING_DIM`. Delete `data/snaprecall.db` and restart the backend to re-index with the new model. |
| **Frontend displays CORS or network errors** | Verify `CORS_ORIGINS` in `.env` includes your frontend URL (e.g., `http://localhost:5173`). In `frontend/.env`, check that `VITE_API_BASE_URL` matches your backend address. |
| **Vector extension (`sqlite-vec`) fails to load** | Your Python build lacks loadable SQLite extension support. On macOS, use python.org or Homebrew Python (`brew install python@3.11`). |
| **Ollama model errors** | Run `ollama list` to verify that `VISION_MODEL` and `EMBEDDING_MODEL` are pulled. Pull them with `ollama pull <model-name>`. |

---

## Roadmap

- Smart filename suggestions with preview, apply, and undo (never silent renames).
- Date and screenshot type filter chips (`payment`, `chat`, `code`, `ticket`).
- Matched text query highlighting directly on preview thumbnails.
- Desktop system tray application with native notifications.
- Benchmark suite for measuring search latency and retrieval quality.

---

## Contributing

Contributions and feedback are welcome!
1. Fork the repository and create a feature branch.
2. In `backend/`, verify tests pass: `pytest` and lint with `ruff check .`.
3. In `frontend/`, run `npm run lint` and `npm run build`.
4. Open a pull request describing your changes.

---

## License

[MIT](LICENSE) © 2026 SnapRecall Contributors