# SnapRecall

**Find any screenshot by typing a few words you remember from it.**
Search your screenshots library using semantic understanding and keyword matching.

> Built for the Hacktoberfest DEV Challenge (theme: "slow and steady"). Supports hosted models through the Google Gemini API (lightweight on your computer) and fully local models through Ollama (private and offline).

---

## The problem

Most of us have thousands of screenshots sitting in a folder, all named like `screenshot_2026-10-24-14-55-16.png`. When you need that one WhatsApp chat, payment confirmation or error message, you end up scrolling through hundreds of thumbnails.

## What SnapRecall does

SnapRecall watches your screenshots folder, reads every image with a vision model and optional OCR, and builds a search index. Later you type whatever you remember ("rahul payment 2500", "wo flight ticket wala", "docker permission error") and the matching screenshots appear.

## Features (MVP)

- **Automatic background indexing** of new screenshots as soon as they are saved.
- **Backfill of your old screenshots**, processed slowly and resumably so your computer stays usable.
- **Hybrid search**: exact keyword match (names, amounts, error codes) combined with semantic search (vague memories, Hinglish queries).
- **Understands screenshot content**: Vision model generates a short summary, tags and the app type (chat, payment, code, ticket, etc.).
- **OCR in English and Hindi** (optional via Tesseract; disabled by default in hosted mode where vision model reads visible text directly).
- **Two model providers**: Hosted Gemini API or 100% local Ollama.
- **Simple web UI** (React) with search box, thumbnail grid, image preview and live indexing progress.

### Roadmap

- Suggested smart filenames with preview, apply and undo (instead of silent renaming).
- Date and app filters.
- Search-as-you-type result highlighting of matched text.
- Desktop tray app and packaged installer.

---

## How it works

```
 Screenshots folder
        |
        v
 [Watcher + Backfill scanner]  --- new / existing files ---> [Job queue (SQLite)]
                                                                   |
                                                    throttled, one image at a time
                                                                   v
                                      +----------------------------------------------+
                                      |  Indexing pipeline                           |
                                      |  1. Load + downscale image                   |
                                      |  2. OCR (optional, Tesseract eng+hin)        |
                                      |  3. Vision model -> summary, tags, app type  |
                                      |  4. Embed text (Gemini or EmbeddingGemma)    |
                                      +----------------------------------------------+
                                                                   |
                                                                   v
                                      SQLite: metadata + FTS5 (keywords) + sqlite-vec (vectors)
                                                                   ^
                                                                   |
 React UI  <---- REST ----  FastAPI  ---- hybrid search (BM25 + vector KNN + rank fusion)
```

**Why hybrid search?** Keyword search is great when you remember an exact word or number but fails on vague memories. Semantic search handles vague memories but can miss exact tokens. Merging both with Reciprocal Rank Fusion gives the best of each.

**Why "slow and steady"?** Indexing a large backlog is resource intensive. The background worker processes one image at a time with a configurable throttle, survives restarts, and resumes where it stopped.

## Tech stack

| Layer | Choice |
|-------|--------|
| Backend | Python, FastAPI |
| Frontend | React (Vite, TypeScript) |
| Model provider | Google Gemini API (hosted) OR Ollama (local) |
| Vision model | Hosted Gemma (e.g. gemma-4-26b-a4b-it) OR local (gemma3:4b) |
| Embeddings | gemini-embedding-001 OR embeddinggemma |
| OCR | Tesseract (English + Hindi, optional) |
| Storage | SQLite with FTS5 and sqlite-vec |
| File watching | watchdog |

---

## Model Providers: Hosted vs Local

SnapRecall supports two distinct model providers configured via `LLM_PROVIDER` in `.env`:

### 1. Hosted Mode (`LLM_PROVIDER=gemini`)
- **How it works:** Screenshots are sent as base64 images over HTTPS to Google Generative Language endpoints (`generateContent` and `batchEmbedContents`).
- **Resource usage:** Very light on your machine (no GPU or heavy RAM requirements).
- **Network requirement:** Requires an active internet connection. Does NOT work offline.
- **Privacy:** Image data and prompts leave your machine and are processed by Google's API.
- **Rate limits and Quotas:** Subject to Google AI Studio rate limits and free-tier daily quotas.
- **Budget Control:** Use `DAILY_REQUEST_BUDGET` to automatically pause processing when you reach a set limit for the day.

### 2. Local Mode (`LLM_PROVIDER=ollama`)
- **How it works:** All models run on your own machine through your local Ollama server.
- **Resource usage:** Requires adequate CPU, RAM, and optionally a GPU.
- **Network requirement:** Once models are pulled, works 100% offline.
- **Privacy:** 100% private. Nothing ever leaves your machine.
- **Limits:** No external rate limits or API quotas.

### Switching Providers or Models
When switching between providers (`gemini` <-> `ollama`) or changing `EMBEDDING_MODEL` or `EMBEDDING_DIM`:
Vectors from different embedding models cannot be compared. SnapRecall stores the active model and dimensions in a `meta` table and refuses to mix vectors. If you change your embedding model or dimensions, delete `data/snaprecall.db` and trigger a scan to rebuild the index.

---

## Getting started

### Prerequisites

- Python 3.11+
- Node.js 20+
- If using `LLM_PROVIDER=gemini`: a Google Gemini API key from https://aistudio.google.com/apikey
- If using `LLM_PROVIDER=ollama`: [Ollama](https://ollama.com) installed and running
- Optional (for `OCR_ENGINE=tesseract`): Tesseract OCR with English and Hindi data

### 1. Configure

```bash
cp .env.example .env
```

Open `.env` and set:
- `SCREENSHOT_DIR` to the absolute path of your screenshots folder.
- `LLM_PROVIDER=gemini` or `LLM_PROVIDER=ollama`.
- If using Gemini, set `GEMINI_API_KEY`.
- If using Ollama, pull your local models:
  ```bash
  ollama pull gemma3:4b
  ollama pull embeddinggemma
  ```

### 2. Run the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs are available at http://localhost:8000/docs.

### 3. Run the frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open http://localhost:5173. Indexing starts automatically if `BACKFILL_ON_START=true`, and the status bar displays live indexing progress.

---

## Configuration

All settings live in `.env` (see `.env.example` for details):

| Variable | Purpose | Default |
|----------|---------|---------|
| `SCREENSHOT_DIR` | Folder to index (required) | none |
| `LLM_PROVIDER` | `gemini` (hosted) or `ollama` (local) | `gemini` |
| `GEMINI_API_KEY` | Gemini API key (required if LLM_PROVIDER=gemini) | empty |
| `GEMINI_BASE_URL` | Gemini API endpoint base | `https://generativelanguage.googleapis.com/v1beta` |
| `OLLAMA_BASE_URL` | Local Ollama endpoint | `http://localhost:11434` |
| `VISION_MODEL` | Vision model name or tag | `gemma-4-26b-a4b-it` |
| `EMBEDDING_MODEL` | Embedding model name or tag | `gemini-embedding-001` |
| `EMBEDDING_DIM` | Vector dimensionality (must match EMBEDDING_MODEL) | `768` |
| `REQUEST_TIMEOUT_SECONDS` | HTTP request timeout for LLM calls | `120` |
| `DAILY_REQUEST_BUDGET` | Max API calls per day before auto-pause (0 = unlimited) | `0` |
| `WORKER_THROTTLE_SECONDS` | Pause between processing images | `6` |
| `OCR_ENGINE` | `none` or `tesseract` | `none` |
| `WATCH_ENABLED` | Index new screenshots automatically | `true` |
| `BACKFILL_ON_START` | Index existing screenshots on startup | `true` |

---

## API overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Aggregate health report, provider connectivity, model availability, and requests today |
| GET | `/api/search?q=...&limit=24` | Hybrid search (keywords and vector semantic ranking) |
| GET | `/api/images/{id}` | Metadata for one screenshot |
| GET | `/api/images/{id}/thumbnail` | Thumbnail image |
| GET | `/api/images/{id}/file` | Original image (indexed files only) |
| GET | `/api/index/status` | Queue size, worker paused reason, and requests today |
| POST | `/api/index/scan` | Trigger a folder scan |
| POST | `/api/index/pause` | Pause background indexing |
| POST | `/api/index/resume` | Resume background indexing |

---

## Privacy and security

- **Local Ollama Mode:** All processing happens locally on your computer. No images or text are transmitted over the internet.
- **Hosted Gemini Mode:** Screenshots and prompt texts are transmitted over HTTPS to the Google Gemini API. Do not use hosted mode if your screenshots contain confidential data that must never leave your machine.
- The SnapRecall backend API binds to `127.0.0.1` by default.
- The `/api/images/{id}/file` endpoint only serves files that exist inside your configured `SCREENSHOT_DIR` and have been indexed into SQLite; arbitrary file system paths are rejected.
- API keys are never returned in health checks or exception messages, and are transmitted strictly via the `x-goog-api-key` HTTP header.

## Why open-source AI?

- **Flexibility:** Run hosted models when you want fast results without stressing your laptop battery, or switch to Ollama when you need complete offline privacy.
- **Control:** Choose and experiment with open-weight models, customize prompts, and adjust vector dimensions.
- **Cost awareness:** Set `DAILY_REQUEST_BUDGET` to stay strictly within free-tier limits without accidental overages.
- **Longevity:** Your personal search index is a standard SQLite database that you own and can inspect, backup, or query directly.

---

## Known limitations

- In hosted mode, you are subject to Google Gemini API availability, rate limits (HTTP 429), and daily request quotas. The worker automatically handles backoff and pauses when limits are exhausted.
- In local Ollama mode, indexing speed depends directly on local hardware capabilities (GPU acceleration, CPU threads, and memory bandwidth).
- `sqlite-vec` requires a Python installation with loadable SQLite extension support.
- If you change your `EMBEDDING_MODEL` or `EMBEDDING_DIM`, you must delete `snaprecall.db` to re-index, as vectors from different models cannot be mixed.

## Contributing

Run `ruff check backend` and `.venv/bin/pytest backend/tests` before submitting code.

## License

MIT. See `LICENSE`.