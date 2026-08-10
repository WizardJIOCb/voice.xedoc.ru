from __future__ import annotations

import os
import io
import json
import shutil
import sqlite3
import hashlib
import hmac
import urllib.error
import urllib.request
import uuid
import wave
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv("VOICE_DATA_DIR", "/app/data"))
DB, AUDIO, VOICES = DATA / "voice.db", DATA / "audio", DATA / "voices"
TOKEN = os.getenv("VOICE_WORKER_TOKEN", "")
MODERATION_KEY = os.getenv("VOICE_MODERATION_KEY", "")
MODERATION_COOKIE = "voice_moderator"
ENGINE_VOICES = {"f5": {"xenia"}, "silero": {"aidar", "baya", "kseniya", "eugene", "xenia"}}
AUDIO.mkdir(parents=True, exist_ok=True)


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    AUDIO.mkdir(parents=True, exist_ok=True)
    VOICES.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, text TEXT NOT NULL, engine TEXT NOT NULL,
          accent_mode TEXT NOT NULL, voice TEXT NOT NULL DEFAULT 'xenia', speed REAL NOT NULL DEFAULT 1.0,
          status TEXT NOT NULL, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, worker_id TEXT, audio_file TEXT, sample_rate INTEGER,
          duration_seconds REAL, accented_text TEXT, error TEXT
        );
        CREATE INDEX IF NOT EXISTS job_status_created ON jobs(status, created_at);
        CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, last_seen TEXT NOT NULL, details TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS voices (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, reference_file TEXT NOT NULL,
          reference_text TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        if "speed" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN speed REAL NOT NULL DEFAULT 1.0")
        if "voice" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN voice TEXT NOT NULL DEFAULT 'xenia'")


@asynccontextmanager
async def life(_: FastAPI):
    init()
    yield


app = FastAPI(title="voice.xedoc.ru", lifespan=life)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount("/audio", StaticFiles(directory=AUDIO), name="audio")


class JobInput(BaseModel):
    # Long books are split into natural chunks by the local worker before F5.
    text: str = Field(min_length=1, max_length=100000)
    engine: str = "f5"
    voice: str = "xenia"
    accent_mode: str = "auto"
    speed: float = Field(default=1.0, ge=0.7, le=1.3)


class Failure(BaseModel):
    error: str = Field(min_length=1, max_length=2000)


class ModerationInput(BaseModel):
    key: str = Field(min_length=1, max_length=200)


class BookBrief(BaseModel):
    premise: str = Field(min_length=12, max_length=3000)
    genre: str = Field(default="лирическая новелла", max_length=120)
    mood: str = Field(default="атмосферный и тёплый", max_length=120)
    hero: str = Field(default="безымянный рассказчик", max_length=240)
    setting: str = Field(default="маленький город поздней осенью", max_length=240)
    length: int = Field(default=4500, ge=2000, le=6000)


def local_book_draft(brief: BookBrief) -> str:
    """Useful editable fallback when no text model is configured."""
    title = brief.premise.split(".", 1)[0].strip()[:70].capitalize()
    paragraphs = [
        f"{title}\n\nВ {brief.setting} {brief.hero} долго откладывал одно простое решение. {brief.premise.strip()}",
        f"Вечер складывался из тихих деталей: влажного света в окнах, редких шагов и запаха дождя. Всё вокруг казалось привычным, но в этой привычности уже жило ожидание перемены.",
        f"{brief.hero.capitalize()} заметил знак почти случайно. Он не обещал ответа, зато заставил остановиться и впервые честно назвать то, от чего раньше удавалось отвернуться.",
        f"Навстречу вышел человек, с которым не нужно было объяснять каждое слово. Их короткий разговор оказался важнее длинных признаний: в нём нашлось место и сомнению, и надежде.",
        f"К полуночи выбор перестал быть отвлечённой мыслью. Он стал дорогой, на которую можно было ступить прямо сейчас, не дожидаясь идеального момента.",
        f"Утром {brief.hero} увидел {brief.setting} иначе. Ничто не изменилось мгновенно, но теперь у каждого шага появилось направление. Так началась история, которую ещё предстояло прожить."
    ]
    # A longer requested draft receives a second, editable story beat.
    if brief.length >= 1500:
        paragraphs.insert(4, "Ночь не торопила событий. Она дала времени развернуться, вспомнить забытое и понять, что смелость редко бывает громкой. Иногда она похожа на письмо, которое наконец решаются отправить.")
    if brief.length >= 2300:
        paragraphs.insert(5, "На рассвете стало ясно: прошлое не исчезает, но перестаёт командовать будущим. Остаётся только бережно принять его и выбрать следующий день своим.")
    return "\n\n".join(paragraphs)


def within_tts_limit(text: str) -> str:
    if len(text) <= 6000:
        return text
    cutoff = max(text.rfind(mark, 0, 6000) for mark in (". ", "! ", "? ", "\n"))
    return text[:cutoff + 1].strip() if cutoff > 4500 else text[:6000].rsplit(" ", 1)[0] + "."


def remote_book_draft(brief: BookBrief) -> str | None:
    endpoint, api_key, model = (os.getenv("BOOK_TEXT_API_URL", "").strip(), os.getenv("BOOK_TEXT_API_KEY", "").strip(), os.getenv("BOOK_TEXT_MODEL", "").strip())
    if not (endpoint and api_key and model):
        return None
    prompt = f"""Напиши законченную русскую новеллу для аудиокниги объёмом около {brief.length} знаков, не больше 6000 знаков.
Жанр: {brief.genre}. Настроение: {brief.mood}. Герой: {brief.hero}. Место и время: {brief.setting}.
Завязка: {brief.premise}.
Нужны ясная арка, живые детали, мягкий финал и литературный русский язык. Не добавляй пояснений, только заголовок и текст новеллы."""
    payload = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.85}).encode("utf-8")
    request = urllib.request.Request(endpoint, data=payload, method="POST", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
        return within_tts_limit(str(body["choices"][0]["message"]["content"]).strip())
    except (urllib.error.URLError, KeyError, IndexError, ValueError):
        return None


def serialize(row: sqlite3.Row) -> dict:
    value = dict(row)
    if value.get("engine") == "f5" and value.get("voice") not in {None, "xenia"}:
        with db() as conn:
            voice = conn.execute("SELECT name FROM voices WHERE id=?", (value["voice"],)).fetchone()
        if voice:
            value["voice_name"] = voice["name"]
    if value.get("audio_file"):
        value["audio_url"] = f"/audio/{value['audio_file']}"
    return value


def auth(authorization: str | None = Header(default=None)) -> None:
    if not TOKEN:
        raise HTTPException(503, "Worker token is not configured")
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "Invalid worker token")


def moderator_cookie() -> str:
    return hashlib.sha256(MODERATION_KEY.encode("utf-8")).hexdigest()


def require_moderator(request: Request) -> None:
    if not MODERATION_KEY or not hmac.compare_digest(request.cookies.get(MODERATION_COOKIE, ""), moderator_cookie()):
        raise HTTPException(403, "Moderation mode is required")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/book", include_in_schema=False)
def book() -> FileResponse:
    return FileResponse(ROOT / "static" / "book.html")


@app.get("/voice", include_in_schema=False)
def voice_page() -> FileResponse:
    return FileResponse(ROOT / "static" / "voice.html")


@app.get("/share/{job_id}", include_in_schema=False)
def share(job_id: str) -> FileResponse:
    return FileResponse(ROOT / "static" / "share.html")


@app.post("/api/book/generate")
def generate_book(brief: BookBrief) -> dict:
    text = remote_book_draft(brief)
    provider = "remote" if text else "template"
    return {"text": text or within_tts_limit(local_book_draft(brief)), "provider": provider}


@app.get("/api/health")
def health() -> dict:
    with db() as conn:
        worker = conn.execute("SELECT * FROM workers ORDER BY last_seen DESC LIMIT 1").fetchone()
        queued = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]
    return {"ok": True, "queued": queued, "worker": dict(worker) if worker else None}


@app.get("/api/moderation/status")
def moderation_status(request: Request) -> dict:
    enabled = bool(MODERATION_KEY) and hmac.compare_digest(request.cookies.get(MODERATION_COOKIE, ""), moderator_cookie())
    return {"enabled": enabled}


@app.post("/api/moderation/enable")
def enable_moderation(payload: ModerationInput, response: Response) -> dict:
    if not MODERATION_KEY or not hmac.compare_digest(payload.key, MODERATION_KEY):
        raise HTTPException(403, "Invalid moderation key")
    response.set_cookie(MODERATION_COOKIE, moderator_cookie(), max_age=60 * 60 * 24 * 30, httponly=True, secure=True, samesite="strict")
    return {"enabled": True}


@app.post("/api/moderation/disable")
def disable_moderation(response: Response) -> dict:
    response.delete_cookie(MODERATION_COOKIE)
    return {"enabled": False}


@app.get("/api/jobs")
def jobs() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 50").fetchall()
    return [serialize(row) for row in rows]


@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Задание не найдено")
    return serialize(row)


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, request: Request) -> Response:
    require_moderator(request)
    with db() as conn:
        row = conn.execute("SELECT status, audio_file FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Job not found")
        if row["status"] == "running":
            raise HTTPException(409, "A running job cannot be deleted")
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    if row["audio_file"]:
        (AUDIO / Path(row["audio_file"]).name).unlink(missing_ok=True)
    return Response(status_code=204)


@app.get("/api/voices")
def voices() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT id, name, created_at FROM voices ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


@app.get("/api/worker/voices/{voice_id}", dependencies=[Depends(auth)])
def voice(voice_id: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT id, name, reference_text, created_at FROM voices WHERE id=?", (voice_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Голос не найден")
    return dict(row)


@app.get("/api/worker/voices/{voice_id}/reference", dependencies=[Depends(auth)])
def voice_reference(voice_id: str) -> FileResponse:
    with db() as conn:
        row = conn.execute("SELECT reference_file FROM voices WHERE id=?", (voice_id,)).fetchone()
    path = VOICES / row["reference_file"] if row else None
    if not path or not path.is_file():
        raise HTTPException(404, "Эталонная запись не найдена")
    return FileResponse(path, media_type="audio/wav", filename=f"{voice_id}.wav")


@app.post("/api/voices", status_code=201)
async def create_voice(
    name: str = Form(...), reference_text: str = Form(...), consent: bool = Form(False), reference: UploadFile = File(...)
) -> dict:
    name, reference_text = name.strip(), reference_text.strip()
    if not consent:
        raise HTTPException(422, "Подтвердите право использовать этот голос")
    if not 2 <= len(name) <= 80 or not 10 <= len(reference_text) <= 2000:
        raise HTTPException(422, "Укажите название голоса и точную расшифровку записи")
    payload = await reference.read(10 * 1024 * 1024 + 1)
    if len(payload) > 10 * 1024 * 1024:
        raise HTTPException(413, "WAV-файл должен быть не больше 10 МБ")
    try:
        with wave.open(io.BytesIO(payload), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
            if wav.getnchannels() not in {1, 2} or not 5 <= duration <= 12:
                raise ValueError
    except (wave.Error, ValueError, ZeroDivisionError):
        raise HTTPException(422, "Нужен WAV длительностью от 5 до 12 секунд без музыки")
    voice_id, created = uuid.uuid4().hex, stamp()
    filename = f"{voice_id}.wav"
    (VOICES / filename).write_bytes(payload)
    with db() as conn:
        conn.execute("INSERT INTO voices (id, name, reference_file, reference_text, created_at) VALUES (?, ?, ?, ?, ?)", (voice_id, name, filename, reference_text, created))
    return {"id": voice_id, "name": name, "created_at": created}


@app.post("/api/jobs", status_code=201)
def create(payload: JobInput) -> dict:
    text = payload.text.strip()
    is_builtin_voice = payload.engine in ENGINE_VOICES and payload.voice in ENGINE_VOICES[payload.engine]
    with db() as conn:
        is_custom_f5_voice = payload.engine == "f5" and conn.execute("SELECT 1 FROM voices WHERE id=?", (payload.voice,)).fetchone()
    if not text or payload.engine not in ENGINE_VOICES or not (is_builtin_voice or is_custom_f5_voice) or payload.accent_mode not in {"auto", "manual"}:
        raise HTTPException(422, "Проверьте текст и параметры задания")
    job_id, created = uuid.uuid4().hex, stamp()
    with db() as conn:
        conn.execute("""
            INSERT INTO jobs (id, text, engine, accent_mode, voice, speed, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)
        """, (job_id, text, payload.engine, payload.accent_mode, payload.voice, payload.speed, created, created))
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return serialize(row)


@app.post("/api/worker/heartbeat", dependencies=[Depends(auth)])
async def heartbeat(request: Request) -> dict:
    body = await request.json()
    worker_id, details = str(body.get("id", "windows-gpu"))[:100], str(body.get("details", ""))[:2000]
    with db() as conn:
        conn.execute("INSERT INTO workers VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen, details=excluded.details", (worker_id, stamp(), details))
    return {"ok": True}


@app.post("/api/worker/jobs/next", dependencies=[Depends(auth)])
async def next_job(request: Request) -> Response:
    worker_id = str((await request.json()).get("id", "windows-gpu"))[:100]
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            conn.commit()
            # HTTP 204 must not have a response body; JSONResponse would send
            # one and corrupt the keep-alive connection used by the worker.
            return Response(status_code=204)
        conn.execute("UPDATE jobs SET status='running', worker_id=?, updated_at=? WHERE id=?", (worker_id, stamp(), row["id"]))
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
        conn.commit()
    return JSONResponse(serialize(row))


@app.post("/api/worker/jobs/{job_id}/complete", dependencies=[Depends(auth)])
async def complete(job_id: str, audio: UploadFile = File(...), sample_rate: int = Form(...), duration_seconds: float = Form(...), accented_text: str = Form(default="")) -> dict:
    path = AUDIO / f"{job_id}.wav"
    with path.open("wb") as file:
        shutil.copyfileobj(audio.file, file)
    with db() as conn:
        row = conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            path.unlink(missing_ok=True)
            raise HTTPException(404, "Задание не найдено")
        conn.execute("UPDATE jobs SET status='complete', audio_file=?, sample_rate=?, duration_seconds=?, accented_text=?, error=NULL, updated_at=? WHERE id=?", (path.name, sample_rate, duration_seconds, accented_text[:100000], stamp(), job_id))
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return serialize(row)


@app.post("/api/worker/jobs/{job_id}/fail", dependencies=[Depends(auth)])
def fail(job_id: str, payload: Failure) -> dict:
    with db() as conn:
        # The worker can lose the response after a successful upload. Do not
        # overwrite an already completed job with that stale failure report.
        conn.execute("UPDATE jobs SET status='failed', error=?, updated_at=? WHERE id=? AND status != 'complete'", (payload.error, stamp(), job_id))
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Задание не найдено")
    return serialize(row)
