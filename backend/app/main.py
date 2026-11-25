import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Optional

import litellm
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from litellm.caching import Cache
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger('lyftr')
logging.basicConfig(level=logging.INFO)
litellm.suppress_debug_info = True


def get_system_prompt():
    current_date = datetime.now(timezone.utc).strftime("%B %d, %Y")

    return (
        "You are Lyftr AI, a helpful and accurate AI assistant. "
        f"The current date is {current_date}. "
        "Use this date when answering time-sensitive questions. "
        "Do not assume your training knowledge is current. "
        "If you cannot verify recent events, clearly state your uncertainty. "
        "Never invent award winners, news, or other recent facts."
    )
MODEL = os.getenv('NVIDIA_MODEL', 'nvidia/nemotron-3-ultra-550b-a55b')
API_BASE = os.getenv('NVIDIA_API_BASE', 'https://integrate.api.nvidia.com/v1')
# Comma-separated NVIDIA credentials, in priority order.
NVIDIA_KEYS = [value.strip() for value in os.getenv('NVIDIA_API_KEYS', '').split(',') if value.strip()]
KEYS = [
    {'id': f'key_{index + 1}', 'provider': 'nvidia', 'api_key': value,
     'model': MODEL, 'api_base': API_BASE}
    for index, value in enumerate(NVIDIA_KEYS)
]
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:////data/app.db')
SIMULATION = os.getenv('ENABLE_FAILURE_SIMULATION', 'false').lower() == 'true'
DB_LOCK = RLock()
CACHE_LOCK = RLock()


def database_path():
    prefix = 'sqlite:///'
    if not DATABASE_URL.startswith(prefix):
        raise RuntimeError('DATABASE_URL must use sqlite:///')
    return DATABASE_URL[len(prefix):]


def db_connection():
    path = database_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=15)
    con.row_factory = sqlite3.Row
    return con


def initialize_db():
    with DB_LOCK, db_connection() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL
        )''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id,id)')
        con.execute('''CREATE TABLE IF NOT EXISTS session_settings (
            session_id TEXT PRIMARY KEY, system_prompt TEXT NOT NULL
        )''')


def load_history(session_id):
    with DB_LOCK, db_connection() as con:
        rows = con.execute('SELECT role,content,metadata FROM messages WHERE session_id=? ORDER BY id', (session_id,)).fetchall()
        return [{'role': row['role'], 'content': row['content'], **({'metadata': json.loads(row['metadata'])} if row['metadata'] else {})} for row in rows]


def stored_prompt(session_id):
    with DB_LOCK, db_connection() as con:
        row = con.execute('SELECT system_prompt FROM session_settings WHERE session_id=?', (session_id,)).fetchone()
        return row['system_prompt'] if row else None


def save_turn(session_id, message, reply, metadata, system_prompt):
    now = datetime.now(timezone.utc).isoformat()
    with DB_LOCK, db_connection() as con:
        con.execute('INSERT OR REPLACE INTO session_settings(session_id,system_prompt) VALUES (?,?)', (session_id, system_prompt))
        con.execute('INSERT INTO messages(session_id,role,content,metadata,created_at) VALUES (?,?,?,?,?)', (session_id, 'user', message, None, now))
        con.execute('INSERT INTO messages(session_id,role,content,metadata,created_at) VALUES (?,?,?,?,?)', (session_id, 'assistant', reply, json.dumps(metadata), now))


# LiteLLM's built-in local cache, with a deterministic full-conversation key.
# Cache API is wrapped to isolate version-specific behavior.
CACHE = Cache(type='local')


def cache_key(messages):
    serialized = json.dumps({'model': MODEL, 'messages': messages}, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return 'lyftr:' + hashlib.sha256(serialized.encode()).hexdigest()


def read_cache(key):
    with CACHE_LOCK:
        value = CACHE.cache.get_cache(key)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def write_cache(key, payload):
    with CACHE_LOCK:
        CACHE.cache.set_cache(key, payload)


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    system_prompt: Optional[str] = None

    @field_validator('session_id', 'message', mode='before')
    @classmethod
    def validate_nonblank(cls, value):
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError('must not be blank')
        return value


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_db()
    yield


app = FastAPI(title='Lyftr AI Chat', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
origins = [x.strip() for x in os.getenv('ALLOWED_ORIGINS', 'http://localhost:3000').split(',') if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'X-Simulate-Failure'])


def parse_simulation(header):
    if not SIMULATION or not header:
        return {}
    result = {}
    for part in header.split(','):
        if '=' not in part:
            continue
        key, status = [x.strip() for x in part.split('=', 1)]
        if (key == '*' or key.startswith('key_')) and status in ('429', '500', '502', '503'):
            result[key] = int(status)
    return result


def retryable(error):
    if isinstance(error, (litellm.RateLimitError, litellm.ServiceUnavailableError, litellm.InternalServerError, litellm.APIConnectionError, litellm.Timeout)):
        return True
    status = getattr(error, 'status_code', None)
    return status == 429 or (isinstance(status, int) and 500 <= status <= 599) or 'quota' in str(error).lower()


@app.get('/health')
def health():
    try:
        with db_connection() as con:
            con.execute('SELECT 1').fetchone()
    except Exception:
        raise HTTPException(status_code=503, detail='database unavailable')
    if len(KEYS) < 2:
        raise HTTPException(status_code=503, detail='key pool unavailable')
    return {'status': 'ok', 'keys_configured': len(KEYS), 'cache_enabled': True}


@app.post('/chat')
async def chat(payload: ChatRequest, x_simulate_failure: Optional[str] = Header(default=None)):
    if len(KEYS) < 2:
        raise HTTPException(status_code=503, detail='all providers unavailable')
    started = time.perf_counter()
    history = load_history(payload.session_id)
    prompt = payload.system_prompt if payload.system_prompt is not None else (stored_prompt(payload.session_id) or get_system_prompt())
    messages = [{'role': 'system', 'content': prompt}] + [{'role': item['role'], 'content': item['content']} for item in history] + [{'role': 'user', 'content': payload.message}]
    simulated = parse_simulation(x_simulate_failure)
    # Failure simulation must exercise the key pool, even for a previously cached prompt.
    allow_cache = not (SIMULATION and bool(x_simulate_failure))
    key = cache_key(messages)
    cached = read_cache(key) if allow_cache else None
    if isinstance(cached, dict) and isinstance(cached.get('reply'), str) and cached['reply']:
        metadata = {'resolution_source': 'LLM_CACHE', 'model': cached['model'], 'latency_ms': int((time.perf_counter() - started) * 1000), 'input_tokens': cached['input_tokens'], 'output_tokens': cached['output_tokens'], 'key_id': None, 'fallback_attempts': 0}
        save_turn(payload.session_id, payload.message, cached['reply'], metadata, prompt)
        return {'session_id': payload.session_id, 'reply': cached['reply'], 'metadata': metadata}

    attempts = 0
    for entry in KEYS:
        key_id = entry['id']
        if key_id in simulated or '*' in simulated:
            attempts += 1
            continue
        try:
            response = await litellm.acompletion(model='openai/' + entry['model'], api_base=entry['api_base'], messages=messages, api_key=entry['api_key'], timeout=60, max_retries=0, caching=False, max_tokens=1000, temperature=0.3)
            reply = response.choices[0].message.content
            if not isinstance(reply, str) or not reply.strip():
                raise ValueError('provider returned empty text')
            usage = response.usage
            input_tokens = int(usage.prompt_tokens or 0)
            output_tokens = int(usage.completion_tokens or 0)
            metadata = {'resolution_source': 'LIVE_INFERENCE', 'model': MODEL, 'latency_ms': int((time.perf_counter() - started) * 1000), 'input_tokens': input_tokens, 'output_tokens': output_tokens, 'key_id': key_id, 'fallback_attempts': attempts}
            write_cache(key, {'reply': reply, 'model': MODEL, 'input_tokens': input_tokens, 'output_tokens': output_tokens})
            save_turn(payload.session_id, payload.message, reply, metadata, prompt)
            return {'session_id': payload.session_id, 'reply': reply, 'metadata': metadata}
        except Exception as error:
            logger.warning('Provider attempt %s failed: %s', key_id, type(error).__name__)
            if not retryable(error):
                logger.warning('Non-retryable provider error for %s', key_id)
            attempts += 1
    raise HTTPException(status_code=503, detail='all providers unavailable')


@app.get('/sessions/{session_id}/messages')
def get_messages(session_id: str):
    if not session_id or len(session_id) > 128:
        raise HTTPException(status_code=404, detail='session not found')
    messages = load_history(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail='session not found')
    return {'session_id': session_id, 'messages': messages}
