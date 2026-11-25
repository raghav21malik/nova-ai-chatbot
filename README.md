# Lyftr AI — Resilient Full-Stack LLM Chatbot

A deployed, multi-turn AI chatbot built with **React (Vite)**, **FastAPI**, **LiteLLM**, **NVIDIA Nemotron 3 Ultra**, and **SQLite**. The application demonstrates API-key failover, response caching, per-request token accounting, and persistent session history.

## 1. Live URLs

| Resource | URL |
| --- | --- |
| Frontend (Vercel) | https://lyftr-ai-chatbot-ashen.vercel.app/ |
| Backend health (Railway) | https://lyftr-ai-chatbot-production-4c958e99.up.railway.app/health |
| Backend base URL | https://lyftr-ai-chatbot-production-4c958e99.up.railway.app |
| Public source repository | https://github.com/siddharth890git/lyftr-ai-chatbot |

The backend root `/` intentionally has no page. Use `/health` to check availability. The public API has three routes: `GET /health`, `POST /chat`, and `GET /sessions/{session_id}/messages`.

## 2. Run locally: with Docker and without

### Requirements

- Docker Desktop with Linux containers, and optionally GNU Make
- Two **valid, separately provisioned** NVIDIA API keys with access to the configured model
- For non-Docker development: Python 3.12+, Node.js and npm

### Environment setup

Create `.env` in the repository root using `.env.example` as a starting point. The current two-NVIDIA-key configuration is:

```dotenv
NVIDIA_API_KEYS=REPLACE_WITH_KEY_1,REPLACE_WITH_KEY_2
NVIDIA_MODEL=nvidia/nemotron-3-ultra-550b-a55b
NVIDIA_API_BASE=https://integrate.api.nvidia.com/v1
DATABASE_URL=sqlite:////data/app.db
ALLOWED_ORIGINS=http://localhost:3000
ENABLE_FAILURE_SIMULATION=true
VITE_API_URL=http://localhost:8000
```

**Never commit `.env` or real API keys.** Use fresh credentials if any older keys were exposed. The Docker Compose service loads `.env` for the backend and mounts a named volume at `/data`.

### With Docker

From the repository root:

```bash
make up
# equivalent without GNU Make:
docker compose up --build -d
```

Visit `http://localhost:3000` for the frontend and `http://localhost:8000/health` for backend health.

```bash
make down
# equivalent:
docker compose down
```

Do **not** run `docker compose down -v` if you want to retain SQLite history.

### Without Docker

Use a writable local database path rather than `/data`:

```bash
cd backend
python -m venv .venv
# Activate the virtual environment for your shell
pip install -r requirements.txt
```

Set the backend variables in your shell, including `NVIDIA_API_KEYS`, `NVIDIA_MODEL`, `NVIDIA_API_BASE`, `DATABASE_URL=sqlite:///./app.db`, `ALLOWED_ORIGINS=http://localhost:3000`, and `ENABLE_FAILURE_SIMULATION=true`, then run:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In another terminal:

```bash
cd frontend
npm install
# Set VITE_API_URL=http://localhost:8000 for the Vite dev server
npm run dev -- --host 0.0.0.0 --port 3000
```

The Vite dev server may use a different port if 3000 is occupied; update `ALLOWED_ORIGINS` accordingly. On Windows PowerShell, `npm.cmd` can be used if execution policy blocks `npm.ps1`.

## 3. Design decisions: key fallback, caching, SQLite session storage

### Architecture

```text
Browser / React (Vercel)
       |
       | HTTPS JSON requests
       v
FastAPI (Railway) -- SQLite (/data/app.db, persistent volume)
       |
       v
LiteLLM completion
       |-- key_1: NVIDIA Nemotron 3 Ultra
       `-- key_2: NVIDIA Nemotron 3 Ultra (fallback)
```

**Key fallback.** The backend loads a comma-separated key pool and attempts keys in order. When a provider reports a retryable rate-limit, quota, connection, timeout, or 5xx error, the request can fall back to the next key. `X-Simulate-Failure` provides a deterministic test hook when `ENABLE_FAILURE_SIMULATION=true`. Metadata includes `key_id` (an identifier, never a credential) and `fallback_attempts`. When no provider succeeds, `/chat` returns HTTP 503 with `{"detail":"all providers unavailable"}`. A failed request is not appended to history.

**Caching.** LiteLLM's built-in local cache is used with a deterministic key based on the model and full LLM message list (system prompt, prior turns, and new user message). A hit returns the saved reply and saved token counts, with `resolution_source=LLM_CACHE`, `key_id=null`, and `fallback_attempts=0`. A new generation returns `LIVE_INFERENCE`. Local in-memory cache is process-local; it is not guaranteed to survive a deployment or restart. A simulated failure request bypasses normal cache lookup so the fallback can be demonstrated.

**Session history.** The client sends only the new message and a session ID. FastAPI reconstructs context from SQLite and saves successful user/assistant turns with assistant metadata. `GET /sessions/{session_id}/messages` returns the session's messages in chronological order, without the system prompt. SQLite is stored on the Docker volume at `/data/app.db`; Railway uses a persistent volume mounted at `/data`. The React recent-chat sidebar keeps a browser-local index of session IDs and retrieves the actual messages from SQLite. That index is specific to the browser and does not synchronize between devices.

**Per-request metadata.** Each assistant reply displays its resolution source, model, latency in milliseconds, input tokens, and output tokens. Token counts are for the current LLM request, not cumulative session totals.

### API contract

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | `status`, `keys_configured`, `cache_enabled` |
| POST | `/chat` | Generate a reply; requires `session_id` and `message`; optional `system_prompt` |
| GET | `/sessions/{session_id}/messages` | Retrieve stored messages and assistant metadata |

Example request:

```json
{"session_id":"demo-session-1","message":"What is 25 multiplied by 16?"}
```

`session_id` must be 1–128 characters; `message` must be 1–4000 characters after trimming. Invalid requests return HTTP 422, unknown sessions return HTTP 404, and exhausted provider pools return HTTP 503. Errors are JSON with a `detail` field.

### Deployment notes

The frontend is built by Vercel from the `frontend/` directory with `VITE_API_URL` set to the public Railway **base** URL (without `/health`). Railway builds `backend/` and receives the NVIDIA credentials as private service environment variables. `ALLOWED_ORIGINS` includes the deployed Vercel origin. Vite variables are public at build time; **never put provider API keys in `VITE_` variables**.

## 4. Verification: how to see failover, cache hits and per-message token usage

### Health

```powershell
Invoke-RestMethod "https://lyftr-ai-chatbot-production-4c958e99.up.railway.app/health"
```

Expected: `status=ok`, `keys_configured=2`, `cache_enabled=true`.

### Successful failover (`key_1=429`)

```powershell
$base = "https://lyftr-ai-chatbot-production-4c958e99.up.railway.app"
$body = @{ session_id = "readme-failover-001"; message = "What is 25 multiplied by 16?" } | ConvertTo-Json
Invoke-RestMethod -Uri "$base/chat" -Method POST -ContentType "application/json" -Headers @{"X-Simulate-Failure"="key_1=429"} -Body $body | ConvertTo-Json -Depth 5
```

Expected metadata: `resolution_source=LIVE_INFERENCE`, `key_id=key_2`, `fallback_attempts=1`, with nonnegative latency and per-request token counts. In a verified production test, the backend returned HTTP 200 with `key_id=key_2`, `fallback_attempts=1`, and a real answer.

### All providers unavailable (`*=429`)

```powershell
$body = @{ session_id = "readme-all-failed-001"; message = "This request should fail." } | ConvertTo-Json
try {
  Invoke-RestMethod -Uri "$base/chat" -Method POST -ContentType "application/json" -Headers @{"X-Simulate-Failure"="*=429"} -Body $body
} catch {
  Write-Host ([int]$_.Exception.Response.StatusCode)
  Write-Host $_.ErrorDetails.Message
}
```

Expected: HTTP 503 and `{"detail":"all providers unavailable"}`. A subsequent GET of `/sessions/readme-all-failed-001/messages` should return HTTP 404 because no turn was saved. This behavior passed local verification.

### Cache hit across sessions

Send the **same first message** in two distinct new sessions, with the same system prompt and without a simulation header:

```powershell
$question = "Explain response caching in one sentence."
foreach ($id in @("readme-cache-a", "readme-cache-b")) {
  $body = @{ session_id = $id; message = $question } | ConvertTo-Json
  Invoke-RestMethod -Uri "$base/chat" -Method POST -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 5
}
```

The first uncached request should show `LIVE_INFERENCE`; the second should show `LLM_CACHE`, identical reply text, `key_id=null`, and lower latency. Cache hits have been observed locally and the automated cache test passed. Cache state can be reset by backend restarts; use fresh unique question text if needed.

### History and persistence

```powershell
Invoke-RestMethod "$base/sessions/readme-failover-001/messages" | ConvertTo-Json -Depth 6
```

The response contains the stored user/assistant messages, including assistant metadata. A production conversation was retrieved successfully **after a Railway backend restart**, confirming persistence on the mounted SQLite volume.

### Backend tests

Run from the repository root on a machine with Python dependencies installed:

```bash
cd backend
python -m pytest -v
```

Six existing backend tests passed locally: health, validation, caching across sessions, multi-turn history, failover/all-failed handling, and system-prompt cache isolation. The production Docker image does not include `tests/` by default; tests should run in a development/test environment, not be assumed discoverable inside the runtime container.

## 5. Setup Used: your editor and AI tools

- **Editor:** Visual Studio Code on Windows; PowerShell for local commands.
- **Development:** Python/FastAPI, React/Vite, LiteLLM, SQLite, Docker Compose, Git and GitHub.
- **AI assistance:** ChatGPT for implementation support, debugging, test guidance, documentation, and deployment troubleshooting.
- **Model provider:** NVIDIA NIM hosted Nemotron 3 Ultra API.
- **Deployment:** Vercel (frontend) and Railway (backend and persistent SQLite volume).

AI-assisted changes were checked through local runtime tests and live deployment verification. API keys are provided through private environment variables and are not intended to be committed.

## 6. Bonus features (if any): what you added beyond the requirements and why

- **Recent chats sidebar:** Browser-local session index with navigation to previous conversations; restores message contents from the required SQLite history endpoint without introducing an extra backend route.
- **Markdown responses:** Renders headings, lists, code blocks, and GitHub-flavored Markdown tables for readability.
- **Session system prompt:** Optional custom instructions; the full system prompt participates in the cache key to avoid cross-prompt cache collisions.
- **New conversation control:** Starts a fresh session without deleting previous SQLite records.

---

### Submission checklist

- [x] Public frontend and backend URLs
- [x] Public GitHub repository
- [x] Two-key simulated failover demonstrated in production
- [x] SQLite history survived a Railway backend restart
- [x] Six backend tests passed locally
- [ ] Confirm no exposed credentials remain valid or tracked in Git history
- [ ] Record and submit a 2–3 minute narrated demo video

**Security note:** The assignment requires `ENABLE_FAILURE_SIMULATION=true` on the deployed backend for evaluation. The public test hook should be restricted or disabled after evaluation when it is no longer needed. Public unauthenticated `/chat` requests may consume provider quota; consider rate limiting and abuse protection for any continued public use.
