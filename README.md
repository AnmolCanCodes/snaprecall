# SnapRecall

**Find any screenshot by typing what you remember about it.**

SnapRecall watches your screenshots folder, lets an AI model read every image in the background, and builds a searchable index. Instead of scrolling through thousands of files named `screenshot_2026-10-24-14-55-16.png`, you type "rahul payment 2500" or "docker permission error" and the matching screenshots appear.

Built for the Hacktoberfest DEV Challenge, Week 3 (theme: "Slow and Steady"). Gemma is the open-weight model at the core of the project.

> **Status: first working version, still being tested.** The design and code are in place, but search quality, Hindi/Hinglish accuracy, large-backlog indexing time and the local (Ollama) mode have not been measured yet. See [Status and limitations](#status-and-limitations).

---

## Table of contents

- [The problem](#the-problem)
- [What SnapRecall does](#what-snaprecall-does)
- [Features](#features)
- [How it works](#how-it-works)
- [Hosted mode vs local mode](#hosted-mode-vs-local-mode)
- [Tech stack](#tech-stack)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [API overview](#api-overview)
- [Project structure](#project-structure)
- [Privacy and security](#privacy-and-security)
- [Why open-weight AI](#why-open-weight-ai)
- [Status and limitations](#status-and-limitations)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## The problem

Screenshots are the fastest way to save something: a payment confirmation, a chat, an error message, a ticket. They are also the hardest thing to find later. Every file has a timestamp for a name, the folder grows into the thousands, and the only way to search it is to scroll through thumbnails and squint.

## What SnapRecall does

1. Watches the folder where your screenshots are saved.
2. Sends each image to a vision model (Gemma), which returns a short summary, tags, the type of screenshot and the text it can read.
3. Stores that information in a local SQLite database, with both a keyword index and a semantic (vector) index.
4. Lets you search in plain language, in English, Hindi or Hinglish, and shows matching screenshots in a thumbnail grid.

Your original files are never renamed, moved or modified.

## Features

- **Background indexing.** New screenshots are picked up automatically shortly after they are saved.
- **Slow and steady backfill.** Existing screenshots are processed one at a time with a configurable pause, so a large backlog never freezes your machine or floods an API.
- **Rate limit aware.** The worker backs off on API rate limits, can pause on a daily request budget, and resumes from where it stopped after a restart.
- **AI understanding of screenshots.** Each image gets a summary, tags, an app type (chat, payment, code, error, ticket, and more) and its visible text.
- **Hybrid search.** Keyword search for exact names, amounts and error codes, combined with semantic search for vague memories, merged with Reciprocal Rank Fusion.
- **English, Hindi and Hinglish queries.**
- **Duplicate detection.** Identical images (by SHA-256) are not processed twice.
- **React web UI.** Search box, thumbnail grid, preview, and live indexing progress with pause and resume.
- **Two model providers.** Hosted Gemma through the Gemini API (light on your laptop) or fully local models through Ollama.

## How it works

```
 Screenshots folder
        |
        v
 [Watcher + folder scanner] --- new / existing files ---> [Job queue in SQLite]
                                                                 |
                                              one image at a time, throttled
                                                                 v
                              +-------------------------------------------------+
                              |  Indexing pipeline                              |
                              |  1. Load and downscale the image                |
                              |  2. Optional OCR (Tesseract, eng+hin)           |
                              |  3. Gemma vision: summary, tags, app type,      |
                              |     visible text                                |
                              |  4. Embed the combined text                     |
                              +-------------------------------------------------+
                                                                 |
                                                                 v
                      SQLite: metadata + FTS5 (keywords) + sqlite-vec (vectors)
                                                                 ^
                                                                 |
 React UI <--- REST ---> FastAPI ---> hybrid search (BM25 + vector KNN + rank fusion)
```

### Why hybrid search

People look for screenshots in two different ways. Sometimes they remember something exact (a name, an amount, an error code), and keyword search is best there because semantic search can blur exact tokens. Other times the memory is vague ("the bus ticket one"), and keyword search fails when the words do not match while semantic search still finds the meaning. SnapRecall runs both and merges the two ranked lists with Reciprocal Rank Fusion, which rewards results that rank well in either list without comparing raw scores.

### Why it is "slow and steady"

Reading thousands of images with a model is heavy. The indexer is designed to be patient:

- One image at a time, with a pause between images (`WORKER_THROTTLE_SECONDS`).
- Retries with exponential backoff when the provider is unavailable or rate-limited. Rate limits are not counted as failed attempts.
- An optional daily request budget (`DAILY_REQUEST_BUDGET`) that pauses indexing automatically.
- Crash recovery: images left in a "processing" state are re-queued on startup.
- Newest screenshots are indexed first, so recent ones become searchable quickly.

## Hosted mode vs local mode

The model layer sits behind a provider switch (`LLM_PROVIDER`). The pipeline, database and UI are identical in both modes.

| | Hosted (`gemini`) | Local (`ollama`) |
|---|---|---|
| Vision model | Gemma 4 through the Gemini API | Gemma through Ollama |
| Embeddings | Hosted embedding model (not open-source) | EmbeddingGemma through Ollama |
| Hardware needed | Any laptop | A machine that can run a vision model |
| Works offline | No | Yes, after models are downloaded |
| Screenshots leave your machine | **Yes**, they are sent to the provider | No |
| Cost | Free tier with limits, then per-request | Electricity only |
| Tested by the author | Yes (primary mode) | Not yet |

Choose hosted mode if your hardware is weak. Choose local mode if your screenshots are sensitive.

## Tech stack

| Layer | Choice |
|-------|--------|
| Backend | Python 3.11+, FastAPI, pydantic v2 |
| Frontend | React 18, Vite, TypeScript |
| Vision model | Gemma (open-weight, multimodal) |
| Embeddings | Gemini embedding model (hosted) or EmbeddingGemma (local) |
| Storage | SQLite with FTS5 and sqlite-vec |
| File watching | watchdog |
| OCR (optional) | Tesseract, English and Hindi |
| HTTP client | httpx |

## Getting started

### Prerequisites

- Python 3.11 or newer (with a SQLite build that supports loadable extensions)
- Node.js 20 or newer
- **Hosted mode:** a Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)
- **Local mode:** [Ollama](https://ollama.com) installed and running
- **Optional OCR:** Tesseract with English and Hindi data
  - Ubuntu/Debian: `sudo apt install tesseract-ocr tesseract-ocr-hin`
  - macOS: `brew install tesseract tesseract-lang`
  - Windows: UB Mannheim installer (tick Hindi), then set `TESSERACT_CMD` in `.env`

### 1. Clone and configure

```bash
git clone https://github.com/AnmolCanCodes/snaprecall.git
cd snaprecall
cp .env.example .env
```

Open `.env` and set at least:

- `SCREENSHOT_DIR`: the folder where your screenshots are saved
- **Hosted mode:** `LLM_PROVIDER=gemini` and `GEMINI_API_KEY=...`
- **Local mode:** `LLM_PROVIDER=ollama`, plus `VISION_MODEL` and `EMBEDDING_MODEL` set to your Ollama tags

Never commit your `.env` file. It is already in `.gitignore`.

### 2. (Local mode only) Pull the models

```bash
ollama pull gemma3:4b
ollama pull embeddinggemma
```

Use any multimodal Gemma tag available in your Ollama library and set it as `VISION_MODEL`.

### 3. Run the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Interactive API docs: http://localhost:8000/docs

### 4. Run the frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open http://localhost:5173. If `BACKFILL_ON_START=true`, indexing begins automatically and the progress bar shows how many screenshots are done.

**Tip:** test with a small folder (10 to 20 screenshots) first. Check `/api/health`, run a search, and only then point `SCREENSHOT_DIR` at your full folder.

## Configuration

All settings live in `.env`. See `.env.example` for the full commented list. The important ones:

| Variable | Purpose | Default |
|----------|---------|---------|
| `SCREENSHOT_DIR` | Folder to index (required) | none |
| `LLM_PROVIDER` | `gemini` or `ollama` | `gemini` |
| `GEMINI_API_KEY` | API key for hosted mode | none |
| `VISION_MODEL` | Model ID used to read screenshots | `gemma-4-26b-a4b-it` |
| `EMBEDDING_MODEL` | Model ID used for embeddings | `gemini-embedding-001` |
| `EMBEDDING_DIM` | Vector size (must match the model) | `768` |
| `OCR_ENGINE` | `tesseract` or `none` | `none` |
| `WATCH_ENABLED` | Index new screenshots automatically | `true` |
| `BACKFILL_ON_START` | Index existing screenshots on startup | `true` |
| `WORKER_THROTTLE_SECONDS` | Pause between images | `6` |
| `DAILY_REQUEST_BUDGET` | Max API calls per day (0 = unlimited) | `0` |
| `MAX_IMAGE_SIDE` | Longest image side sent to the model (px) | `1024` |

Confirm exact model IDs in Google AI Studio (or your Ollama library) before running, since available models change over time.

> **Important:** if you change `EMBEDDING_MODEL` or `EMBEDDING_DIM`, delete `data/snaprecall.db` and re-index. Vectors from different models must never be mixed, and the backend refuses to index when it detects a mismatch.

## API overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Provider status, model availability, config problems, request counters |
| GET | `/api/search?q=...&limit=24` | Hybrid search (empty query returns recent screenshots) |
| GET | `/api/images/{id}` | Metadata for one screenshot |
| GET | `/api/images/{id}/thumbnail` | Thumbnail |
| GET | `/api/images/{id}/file` | Original image (indexed files only) |
| GET | `/api/index/status` | Queue counts, current file, paused state and reason |
| POST | `/api/index/scan` | Trigger a folder scan |
| POST | `/api/index/pause` | Pause the worker |
| POST | `/api/index/resume` | Resume the worker |

If the semantic leg is unavailable, search falls back to keyword-only and sets a `degraded` flag in the response.

## Project structure

```
snaprecall/
  backend/
    app/
      main.py              FastAPI app and lifespan (starts watcher and worker)
      config.py            Settings loaded from the root .env
      db.py                SQLite connection, schema, FTS5 and vector tables
      schemas.py           Pydantic request and response models
      api/                 Route modules: health, search, images, index
      services/            LLM clients, OCR, vision, embeddings, pipeline,
                           worker, watcher, hybrid search
      utils/               Hashing, image helpers, logging
    tests/
    requirements.txt
    requirements-dev.txt
  frontend/
    src/                   React app: components, hooks, API client
  data/                    Created at runtime (database, thumbnails), git-ignored
  .env.example
  README.md
```

## Privacy and security

Be clear about which mode you are using:

- **Hosted mode sends your screenshots to the model provider.** Do not use it for images containing sensitive information unless you accept the provider's terms. Free-tier terms in particular may allow your inputs to be used to improve their products. Read them before indexing anything private.
- **Local mode keeps everything on your machine.** Models run through your own Ollama server and no image data leaves it.
- Your API key is read only from `.env`, sent only in a request header, and never logged or returned by the API.
- The API binds to `127.0.0.1` by default.
- The file endpoint resolves files by database id only and verifies the path is inside `SCREENSHOT_DIR`, so arbitrary paths cannot be requested.
- The database and thumbnails stay in `DATA_DIR`, which is git-ignored.

## Why open-weight AI

- **Choice of where it runs.** Because Gemma's weights are open, the same model is available as a hosted API for weak hardware and as a local model for people who want privacy. A closed vision API offers only the hosted path.
- **A private path exists.** Screenshots contain OTPs, bank details and personal chats. Open weights make it possible to process them without sending them anywhere.
- **Predictable cost.** Locally, indexing thousands of images costs only electricity, and re-indexing is free. Per-image API pricing adds up for a tool whose job is to process thousands of images.
- **Control.** You can swap models, change quantization or move providers without rewriting the application.

An honest note: in hosted mode the embeddings come from a hosted model that is not open-source, and no benchmark against closed vision models has been done, so no claim is made that Gemma reads screenshots better than they do. The advantage claimed here is flexibility and the existence of a private option.

## Status and limitations

This is a first version and still needs testing. Not yet measured or verified:

- Search accuracy on a large, real screenshot collection
- How well Hindi and Hinglish screenshots are read
- Indexing time for a large backlog under free-tier limits
- The local (Ollama) mode on real hardware
- How much time the tool actually saves in daily use

Known constraints:

- Hosted free tiers have low request limits, so a large backlog will take many days unless you use a paid tier. Use `DAILY_REQUEST_BUDGET` and `WORKER_THROTTLE_SECONDS` to stay within limits.
- Small screenshots of dense text may be read imperfectly after downscaling. Raise `MAX_IMAGE_SIDE` if needed (at higher request cost).
- `sqlite-vec` needs a Python build whose SQLite supports loadable extensions. On macOS, use Homebrew or python.org Python if loading fails.
- The backend must run on the machine that holds the screenshots. Hosting it remotely would need an upload feature, which does not exist yet.

## Troubleshooting

| Problem | Likely cause and fix |
|---------|----------------------|
| `/api/health` says the API key is missing | `GEMINI_API_KEY` is empty in the root `.env`. Set it and restart the backend. |
| Nothing is being indexed | `SCREENSHOT_DIR` is empty or wrong, or the worker is paused. Check `/api/health` and `/api/index/status`. |
| Indexing paused by itself | Daily quota or `DAILY_REQUEST_BUDGET` reached. It resumes at local midnight, or click Resume. |
| `embedding_mismatch` in health | You changed the embedding model or dimension. Delete `data/snaprecall.db` and re-index. |
| Frontend shows a network or CORS error | Add your frontend origin to `CORS_ORIGINS`. Note that `localhost` and `127.0.0.1` are different origins. |
| Vector extension fails to load | Use a Python build with SQLite extension loading enabled (see Limitations). |

## Roadmap

- Smart filename suggestions with preview, apply and undo (never silent renames)
- Filters by date and screenshot type
- Highlighting of matched text in results
- Evaluation script: a small set of test queries to measure search quality
- Tested local mode with published timings
- Desktop tray app and packaged installer

## Contributing

Issues and pull requests are welcome. Before opening a PR, run `ruff check .` and `pytest` inside `backend/`, and `npm run lint` and `npm test` inside `frontend/`. If something breaks on your screenshots, please open an issue with the error message and your provider mode.

## License

MIT. See `LICENSE`.