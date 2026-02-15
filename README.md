# Notion Connection API

Production-ready FastAPI service for task capture from iPhone Shortcuts, with async job processing via Redis and Notion integration.

## Architecture

- **Web Service** (FastAPI): Accepts POST `/capture_async`, enqueues jobs to Redis, returns `job_id` and status URL.
- **Background Worker**: Consumes jobs from Redis, runs Stage A (planning) → optional Stage B (deep research) → Notion page creation.
- **Redis**: Job queue (`queue:jobs`) + ephemeral job status/results (`job:{job_id}`) with 6h TTL. No database.

## Local Run

### Prerequisites

- Python 3.14 (or 3.11+)
- Redis running locally

### Setup

```bash
cd notion-connection-api
python3.14 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys and Redis URL
```

### Start services

**Terminal 1 – Web Service:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Terminal 2 – Worker:**
```bash
python -m app.worker
```

## Render Deploy

### 1. Create Redis instance

- Render Dashboard → New → Redis
- Note the **Internal Redis URL** (e.g. `redis://red-xxx:6379`)

### 2. Create Web Service

- New → Web Service
- Connect your repo (root: `notion-connection-api`)
- **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Environment variables:**
  - `API_KEY`, `NOTION_INTEGRATION_SECRET`, `NOTION_DATABASE_ID`
  - `OPENAI_API_KEY`, `OPENAI_PROJECT_ID`
  - `REDIS_URL` (Internal Redis URL)
  - Optional: `MODEL_PLAN`, `MODEL_RESEARCH`, `JOB_TTL_SECONDS`, `NOTION_TITLE_PROP`, `NOTION_DUE_PROP`

### 3. Create Background Worker

- New → Background Worker
- Same repo, same root
- **Start command:** `python -m app.worker`
- Same environment variables as Web Service (especially `REDIS_URL`)

## API Endpoints

### GET /health

```json
{ "ok": true }
```

### POST /capture_async

**Headers:** `X-API-Key: <API_KEY>`, `Content-Type: application/json`

**Request:**
```json
{
  "task_name": "Complete Notion Connection App",
  "client_time": "2026-02-11T01:39:51+08:00",
  "task_content": "Research on the possible architecture and then execute on Cursor to build the application base codes",
  "source": "shortcut",
  "task_date": "2026-02-13T01:38:00+08:00"
}
```

**Response:**
```json
{
  "ok": true,
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status_url": "/jobs/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

### GET /jobs/{job_id}

**Headers:** `X-API-Key: <API_KEY>`

**Response (queued):**
```json
{
  "status": "queued",
  "created_at": "2026-02-15T12:00:00.000Z",
  "payload": {
    "task_name": "Complete Notion Connection App",
    "client_time": "2026-02-11T01:39:51+08:00",
    "task_content": "...",
    "source": "shortcut",
    "task_date": "2026-02-13T01:38:00+08:00"
  }
}
```

**Response (running):**
```json
{
  "status": "running",
  "started_at": "2026-02-15T12:00:01.000Z",
  "payload": { ... }
}
```

**Response (succeeded):**
```json
{
  "status": "succeeded",
  "finished_at": "2026-02-15T12:01:30.000Z",
  "notion": {
    "page_id": "abc123...",
    "page_url": "https://www.notion.so/..."
  },
  "plan": { "need_deep_research": false, "human_todos": [...], ... },
  "deep_research": null
}
```

**Response (failed):**
```json
{
  "status": "failed",
  "finished_at": "2026-02-15T12:00:05.000Z",
  "error": "OpenAI API error: ..."
}
```

**404 when job not found or expired:**
```json
{
  "ok": false,
  "error": "Job not found or expired"
}
```

## curl Examples

```bash
# Health
curl -s https://your-service.onrender.com/health

# Enqueue task
curl -X POST https://your-service.onrender.com/capture_async \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "task_name": "My Task",
    "client_time": "2026-02-15T12:00:00+00:00",
    "task_content": "Do something",
    "source": "shortcut",
    "task_date": "2026-02-16T12:00:00+00:00"
  }'

# Poll job status (replace JOB_ID)
curl -s https://your-service.onrender.com/jobs/JOB_ID \
  -H "X-API-Key: YOUR_API_KEY"
```

## iPhone Shortcuts Setup

1. **Shortcut 1 – Capture task**
   - Action: Get Contents of URL
   - URL: `https://your-service.onrender.com/capture_async`
   - Method: POST
   - Headers: `X-API-Key: YOUR_API_KEY`, `Content-Type: application/json`
   - Request body: JSON
     ```json
     {
       "task_name": "{{Shortcut Input}}",
       "client_time": "{{Current Date}}",
       "task_content": "{{Shortcut Input}}",
       "source": "shortcut",
       "task_date": "{{Current Date}}"
     }
     ```
   - Parse JSON from response → extract `job_id`

2. **Shortcut 2 – Poll until done**
   - Repeat: Get Contents of URL `https://your-service.onrender.com/jobs/{{job_id}}` with `X-API-Key`
   - Parse JSON → if `status == "succeeded"`, show `notion.page_url` and exit
   - Wait 5–10 seconds between polls
   - Optional: timeout after N attempts

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_KEY` | Yes | - | API key for X-API-Key header |
| `NOTION_INTEGRATION_SECRET` | Yes | - | Notion integration token |
| `NOTION_DATABASE_ID` | Yes | - | Target database ID |
| `NOTION_TITLE_PROP` | No | Name | Title property name |
| `NOTION_DUE_PROP` | No | - | Due date property name (optional) |
| `NOTION_VERSION` | No | 2022-06-28 | Notion API version |
| `OPENAI_API_KEY` | Yes | - | OpenAI API key |
| `OPENAI_PROJECT_ID` | No | - | OpenAI project/org ID |
| `MODEL_PLAN` | No | gpt-4o-mini | Planning model |
| `MODEL_RESEARCH` | No | gpt-4o | Deep research model |
| `REDIS_URL` | Yes | - | Redis connection URL |
| `JOB_TTL_SECONDS` | No | 21600 | Job TTL (6 hours) |

## Pipeline

- **Stage A**: OpenAI Responses API → plan with `need_deep_research`, `human_todos`, `notion_page_title`, etc.
- **Stage B** (if `need_deep_research`): Deep research model → `research_summary`, `key_takeaways`, `sources`
- **Notion**: Create page in database with title, due date (if configured), task content, summary, todos, and optional deep research section.
