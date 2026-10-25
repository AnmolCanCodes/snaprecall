# SnapRecall

**Find any screenshot by typing a few words you remember from it.**
Local, private, open-source AI that quietly indexes your screenshots in the background.

> Built for the Hacktoberfest DEV Challenge (theme: "slow and steady"). Everything runs on your own machine with open-weight Gemma models. No cloud, no API keys, no subscription.

---

## The problem

Most of us have thousands of screenshots sitting in a folder, all named like `screenshot_2026-10-24-14-55-16.png`. When you need that one WhatsApp chat, payment confirmation or error message, you end up scrolling through hundreds of thumbnails.

## What SnapRecall does

SnapRecall watches your screenshots folder, reads every image with a local vision model and OCR, and builds a private search index. Later you type whatever you remember ("rahul payment 2500", "wo flight ticket wala", "docker permission error") and the matching screenshots appear.

## Features (MVP)

- **Automatic background indexing** of new screenshots as soon as they are saved.
- **Backfill of your old screenshots**, processed slowly and resumably so your computer stays usable.
- **Hybrid search**: exact keyword match (names, amounts, error codes) combined with semantic search (vague memories, Hinglish queries).
- **Understands screenshot content**: Gemma generates a short summary, tags and the app type (chat, payment, code, ticket, etc.).
- **OCR in English and Hindi** for exact text lookup.
- **100% local**: nothing leaves your machine.
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
                                      |  2. OCR (Tesseract, eng+hin)                 |
                                      |  3. Gemma vision -> summary, tags, app type  |
                                      |  4. Embed combined text (EmbeddingGemma)     |
                                      +----------------------------------------------+
                                                                   |
                                                                   v
                                      SQLite: metadata + FTS5 (keywords) + sqlite-vec (vectors)
                                                                   ^
                                                                   |
 React UI  <---- REST ----  FastAPI  ---- hybrid search (BM25 + vector KNN + rank fusion)
```

**Why hybrid search?** Keyword search is great when you remember an exact word or number but fails on vague memories. Semantic search handles vague memories but can miss exact tokens. Merging both with Reciprocal Rank Fusion gives the best of each.

**Why "slow and steady"?** Indexing a large backlog with a local model is heavy. The worker processes one image at a time with a configurable pause, survives restarts, and resumes where it stopped. You can keep working while it runs.

## Tech stack

| Layer | Choice |
|-------|--------|
| Backend | Python, FastAPI |
| Frontend | React (Vite, TypeScript) |
| Vision model | Gemma (multimodal) via Ollama |
| Embeddings | EmbeddingGemma via Ollama |
| OCR | Tesseract (English + Hindi) |
| Storage | SQLite with FTS5 and sqlite-vec |
| File watching | watchdog |

---

## Getting started

### Prerequisites

- Python 3.11+
- Node.js 20+
- [Ollama](https://ollama.com) installed and running
- Tesseract OCR with English and Hindi data:
  - Ubuntu/Debian: `sudo apt install tesseract-ocr tesseract-ocr-hin`
  - macOS: `brew install tesseract tesseract-lang`
  - Windows: install from the UB Mannheim build, tick Hindi during setup, then set `TESSERACT_CMD` in `.env`

### 1. Pull the models

```bash
ollama pull gemma3:4b
ollama pull embeddinggemma
```

Prefer a different Gemma tag? Change `VISION_MODEL` in `.env`.

### 2. Configure

```bash
cp .env.example .env
```

Open `.env` and set `SCREENSHOT_DIR` to the folder where your screenshots are saved.

### 3. Run the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs are available at http://localhost:8000/docs.

### 4. Run the frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open http://localhost:5173. Indexing starts automatically if `BACKFILL_ON_START=true`, and the progress bar shows how many screenshots are done.

---

## Configuration

All settings live in `.env` (see `.env.example` for the full list with comments). The important ones:

| Variable | Purpose | Default |
|----------|---------|---------|
| `SCREENSHOT_DIR` | Folder to index (required) | none |
| `WATCH_ENABLED` | Index new screenshots automatically | `true` |
| `BACKFILL_ON_START` | Index existing screenshots on startup | `true` |
| `VISION_MODEL` | Ollama tag of the Gemma vision model | `gemma3:4b` |
| `EMBEDDING_MODEL` | Ollama tag of the embedding model | `embeddinggemma` |
| `OCR_LANGS` | Tesseract languages | `eng+hin` |
| `WORKER_THROTTLE_SECONDS` | Pause between images | `2` |
| `MAX_IMAGE_SIDE` | Longest side sent to the model (px) | `1280` |

## API overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Server, database and Ollama status |
| GET | `/api/search?q=...&limit=24` | Hybrid search |
| GET | `/api/images/{id}` | Metadata for one screenshot |
| GET | `/api/images/{id}/thumbnail` | Thumbnail |
| GET | `/api/images/{id}/file` | Original image (indexed files only) |
| GET | `/api/index/status` | Queue size, processed count, current state |
| POST | `/api/index/scan` | Trigger a folder scan |
| POST | `/api/index/pause` | Pause the worker |
| POST | `/api/index/resume` | Resume the worker |

## Project structure

```
snaprecall/
  backend/
    app/
      main.py            FastAPI app, lifespan (starts watcher + worker)
      config.py          Settings loaded from .env
      db.py              SQLite connection, schema, migrations
      schemas.py         Pydantic request/response models
      api/               Route modules (search, images, index, health)
      services/          OCR, vision, embeddings, pipeline, worker, watcher, search
      utils/             Hashing, image helpers, logging
    tests/
    requirements.txt
  frontend/
    src/                 React app (components, hooks, API client)
  data/                  Created at runtime (database, thumbnails), git-ignored
```

## Privacy and security

- All processing happens locally. Models run through your own Ollama server.
- The API binds to `127.0.0.1` by default.
- The file endpoint only serves files that are in the index, so arbitrary paths cannot be requested.
- The database and thumbnails stay in `DATA_DIR`, which is git-ignored.

## Why open-source AI?

- **Privacy:** screenshots contain OTPs, bank details and private chats. Sending them to a hosted API is not an option for many people.
- **Offline:** once the models are pulled, everything works without internet.
- **One-time cost:** no per-image API fees, which matters when indexing thousands of images and re-indexing after changes.
- **Control:** swap models, quantize them, or run on modest hardware without rate limits.

## Known limitations

- Indexing speed depends on your hardware. A CPU-only machine will take a while on a large backlog.
- Hindi OCR quality depends on the screenshot (stylised fonts and low contrast hurt accuracy). Gemma's own text reading acts as a fallback.
- `sqlite-vec` needs a Python build whose SQLite supports loadable extensions. If loading fails on macOS, use the Homebrew or python.org Python.

## Contributing

Issues and pull requests are welcome. Run `ruff check .` and `pytest` inside `backend/` before opening a PR.

## License

MIT. See `LICENSE`.