from __future__ import annotations

import json
import logging
import os
import re
import socket
import tempfile
import time
import traceback
from pathlib import Path

import numpy as np
import requests
import soundfile as sf
import torch

ROOT = Path(__file__).resolve().parents[1]
MODELS, RUNTIME, DATA = ROOT / "models", ROOT / ".runtime", ROOT / "data"
RUNTIME.mkdir(exist_ok=True)
logging.basicConfig(filename=RUNTIME / "worker.log", level=logging.INFO, encoding="utf-8", format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("voice")


def load_env() -> None:
    path = ROOT / "worker" / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


load_env()
SERVER = os.getenv("VOICE_SERVER_URL", "https://voice.xedoc.ru").rstrip("/")
WORKER_ID = os.getenv("VOICE_WORKER_ID", f"windows-{socket.gethostname()}")
TOKEN_FILE = RUNTIME / "worker.token"
if not TOKEN_FILE.exists():
    raise RuntimeError(f"Missing {TOKEN_FILE}")
HTTP = requests.Session()
HTTP.headers["Authorization"] = f"Bearer {TOKEN_FILE.read_text(encoding='utf-8').strip()}"
MAX_TTS_CHUNK = 4500
CHUNK_PAUSE_SECONDS = 0.35


def request(method: str, path: str, *, timeout: tuple[int, int] = (20, 600), **kwargs) -> requests.Response:
    response = HTTP.request(method, SERVER + path, timeout=timeout, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path}: {response.status_code} {response.text[:400]}")
    return response


def f5_reference(voice: str) -> tuple[Path, str]:
    """Get a built-in reference or cache a user-created voice from the server."""
    if voice == "xenia":
        reference = MODELS / "reference" / "xenia.wav"
        text_path = ROOT / "worker" / "reference_text.txt"
        if not reference.exists():
            raise RuntimeError("Reference WAV is unavailable")
        return reference, text_path.read_text(encoding="utf-8").strip()

    folder = MODELS / "reference" / "custom"
    reference = folder / f"{voice}.wav"
    text_path = folder / f"{voice}.txt"
    if not reference.exists() or not text_path.exists():
        metadata = request("GET", f"/api/worker/voices/{voice}").json()
        audio = request("GET", f"/api/worker/voices/{voice}/reference").content
        folder.mkdir(parents=True, exist_ok=True)
        reference.write_bytes(audio)
        text_path.write_text(metadata["reference_text"], encoding="utf-8")
        LOG.info("Cached custom F5 voice %s (%s)", voice, metadata["name"])
    # Browser recordings often start/end with a second of silence. It weakens
    # F5 conditioning, so keep a small natural margin and remove the rest.
    audio, rate = sf.read(reference, dtype="float32")
    amplitude = np.max(np.abs(audio), axis=1) if np.ndim(audio) == 2 else np.abs(audio)
    active = np.flatnonzero(amplitude > 0.012)
    if len(active):
        start = max(0, active[0] - round(rate * 0.12))
        end = min(len(audio), active[-1] + round(rate * 0.25))
        trimmed = audio[start:end]
        if len(trimmed) >= rate * 5 and len(trimmed) < len(audio):
            sf.write(reference, trimmed, rate, subtype="PCM_16")
            LOG.info("Trimmed silence from custom F5 voice %s", voice)
    return reference, text_path.read_text(encoding="utf-8").strip()


class Accent:
    model = None

    def apply(self, text: str) -> str:
        if self.model is None:
            from ruaccent import RUAccent
            dictionary = DATA / "custom_dictionary.json"
            custom = json.loads(dictionary.read_text(encoding="utf-8")) if dictionary.exists() else {}
            self.model = RUAccent()
            LOG.info("Loading RUAccent turbo3.1")
            self.model.load(omograph_model_size="turbo3.1", use_dictionary=True, custom_dict=custom, tiny_mode=False, device="CPU", workdir=str(MODELS / "ruaccent"))
        return self.model.process_all(text)


class F5:
    model = None

    def make(self, text: str, output: Path, speed: float, voice: str = "xenia") -> tuple[int, float]:
        if self.model is None:
            from f5_tts.api import F5TTS
            checkpoint = MODELS / "f5" / "F5TTS_v1_Base_v2" / "model_last_inference.safetensors"
            vocab = MODELS / "f5" / "F5TTS_v1_Base" / "vocab.txt"
            if not checkpoint.exists() or not torch.cuda.is_available():
                raise RuntimeError("F5 checkpoint or CUDA is unavailable")
            LOG.info("Loading F5 on %s", torch.cuda.get_device_name(0))
            self.model = F5TTS(model="F5TTS_v1_Base", ckpt_file=str(checkpoint), vocab_file=str(vocab), device="cuda", hf_cache_dir=str(MODELS / "hf-cache"))
        ref, ref_text = f5_reference(voice)
        # The Russian F5 checkpoint expects stressed vowels in its reference
        # transcription too. The built-in Xenia reference is already marked.
        if voice != "xenia":
            ref_text = accent.apply(ref_text)
        # F5's automatic duration estimate is unreliable for very short
        # Russian phrases and may cut them after the first word.  Reserve a
        # natural speech duration explicitly; `fix_duration` includes the
        # reference itself, which F5 removes from the final waveform.
        # F5 itself clips a reference at 12 seconds. Use the same ceiling
        # here so `fix_duration` matches the audio F5 will actually condition
        # on, rather than a longer original browser recording.
        reference_seconds = min(sf.info(ref).duration, 12.0)
        speech_seconds = max(1.2, len(text.replace("+", "")) / (14.0 * speed))
        wave, rate, _ = self.model.infer(
            ref_file=str(ref), ref_text=ref_text, gen_text=text,
            nfe_step=32, cfg_strength=2.0, sway_sampling_coef=-1.0,
            speed=speed, fix_duration=reference_seconds + speech_seconds,
            file_wave=str(output), seed=20260803,
        )
        return rate, len(np.asarray(wave)) / rate


def split_tts_text(text: str, limit: int = MAX_TTS_CHUNK) -> list[str]:
    """Split a book at paragraphs/sentences without cutting a word in half."""
    remaining = text.strip()
    chunks: list[str] = []
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        window = remaining[:limit + 1]
        boundaries = [match.end() for match in re.finditer(r"(?:[.!?…]+[»”\"']?\s+|\n+)", window)]
        cut = boundaries[-1] if boundaries else window.rfind(" ")
        if cut < limit // 3:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].lstrip()
    return chunks


def make_book_audio(engine: F5 | "Silero", text: str, output: Path, speed: float, voice: str) -> tuple[int, float]:
    parts = split_tts_text(text)
    if len(parts) == 1:
        return engine.make(parts[0], output, speed, voice)

    waves: list[np.ndarray] = []
    sample_rate: int | None = None
    with tempfile.TemporaryDirectory(prefix="voice-parts-") as folder:
        for index, part in enumerate(parts, start=1):
            part_output = Path(folder) / f"part-{index}.wav"
            LOG.info("Rendering part %s/%s (%s characters)", index, len(parts), len(part))
            rate, _ = engine.make(part, part_output, speed, voice)
            wave, actual_rate = sf.read(part_output, dtype="float32")
            if sample_rate is None:
                sample_rate = actual_rate
            elif actual_rate != sample_rate or rate != sample_rate:
                raise RuntimeError("TTS returned audio chunks with different sample rates")
            waves.append(np.asarray(wave, dtype=np.float32))
            if index < len(parts):
                waves.append(np.zeros(round(sample_rate * CHUNK_PAUSE_SECONDS), dtype=np.float32))
    if sample_rate is None:
        raise RuntimeError("No audio chunks were rendered")
    combined = np.concatenate(waves)
    sf.write(output, combined, sample_rate, subtype="PCM_16")
    return sample_rate, len(combined) / sample_rate


class Silero:
    model = None

    def make(self, text: str, output: Path, speed: float, voice: str = "xenia") -> tuple[int, float]:
        if self.model is None:
            path = MODELS / "silero" / "v5_5_ru.pt"
            if not path.exists():
                raise RuntimeError("Silero checkpoint is unavailable")
            torch.set_num_threads(8)
            self.model = torch.package.PackageImporter(str(path)).load_pickle("tts_models", "model")
            self.model.to(torch.device("cpu"))
        rate, pause = 48000, np.zeros(16800, dtype=np.float32)
        chunks = []
        for sentence in [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if item.strip()]:
            audio = self.model.apply_tts(text=sentence, speaker=voice, sample_rate=rate).detach().cpu().numpy().astype(np.float32)
            chunks.extend((audio, pause))
        wave = np.concatenate(chunks[:-1])
        if speed != 1.0:
            import librosa
            wave = librosa.effects.time_stretch(wave, rate=speed)
        peak = float(np.max(np.abs(wave)))
        if peak:
            wave *= .92 / peak
        sf.write(output, wave, rate, subtype="PCM_16")
        return rate, len(wave) / rate


accent, f5, silero = Accent(), F5(), Silero()


def heartbeat() -> None:
    details = {"host": socket.gethostname(), "cuda": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "unavailable", "engines": ["f5", "silero"]}
    request("POST", "/api/worker/heartbeat", json={"id": WORKER_ID, "details": json.dumps(details, ensure_ascii=False)})


def execute(job: dict) -> None:
    accented = accent.apply(job["text"].strip()) if job["accent_mode"] == "auto" else job["text"].strip()
    engine = f5 if job["engine"] == "f5" else silero
    with tempfile.TemporaryDirectory(prefix="voice-") as folder:
        output = Path(folder) / f"{job['id']}.wav"
        parts = split_tts_text(accented)
        LOG.info("Rendering %s as %s part(s)", job["id"], len(parts))
        rate, duration = make_book_audio(engine, accented, output, float(job.get("speed", 1.0)), job.get("voice", "xenia"))
        for attempt in range(3):
            try:
                # Reopen the WAV for every attempt: a partially sent multipart
                # stream cannot be reused after a connection interruption.
                with output.open("rb") as file:
                    # requests has no separate write timeout; its connect value
                    # also limits socket writes. A long F5 WAV needs more than
                    # the 20 seconds appropriate for small polling requests.
                    request("POST", f"/api/worker/jobs/{job['id']}/complete", timeout=(600, 600), files={"audio": (output.name, file, "audio/wav")}, data={"sample_rate": rate, "duration_seconds": f"{duration:.3f}", "accented_text": accented})
                break
            except Exception:
                if attempt == 2:
                    raise
                LOG.warning("Upload of %s failed; retrying (%s/3)", job["id"], attempt + 1)
                time.sleep(3)
    LOG.info("Completed %s", job["id"])


def main() -> None:
    LOG.info("Worker %s started for %s", WORKER_ID, SERVER)
    beat = 0.0
    while True:
        job = None
        try:
            if time.monotonic() - beat > 20:
                heartbeat(); beat = time.monotonic()
            response = request("POST", "/api/worker/jobs/next", json={"id": WORKER_ID})
            if response.status_code == 204:
                time.sleep(2); continue
            job = response.json()
            execute(job)
        except KeyboardInterrupt:
            return
        except Exception as error:
            LOG.exception("Worker error")
            if job:
                try: request("POST", f"/api/worker/jobs/{job['id']}/fail", json={"error": str(error)})
                except Exception: LOG.error(traceback.format_exc())
            time.sleep(5)


if __name__ == "__main__":
    main()
