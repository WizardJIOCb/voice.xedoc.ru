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


def request(method: str, path: str, *, timeout: tuple[int, int] = (20, 600), **kwargs) -> requests.Response:
    response = HTTP.request(method, SERVER + path, timeout=timeout, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path}: {response.status_code} {response.text[:400]}")
    return response


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

    def make(self, text: str, output: Path) -> tuple[int, float]:
        if self.model is None:
            from f5_tts.api import F5TTS
            checkpoint = MODELS / "f5" / "F5TTS_v1_Base_v2" / "model_last_inference.safetensors"
            vocab = MODELS / "f5" / "F5TTS_v1_Base" / "vocab.txt"
            if not checkpoint.exists() or not torch.cuda.is_available():
                raise RuntimeError("F5 checkpoint or CUDA is unavailable")
            LOG.info("Loading F5 on %s", torch.cuda.get_device_name(0))
            self.model = F5TTS(model="F5TTS_v1_Base", ckpt_file=str(checkpoint), vocab_file=str(vocab), device="cuda", hf_cache_dir=str(MODELS / "hf-cache"))
        ref = MODELS / "reference" / "xenia.wav"
        ref_text = (ROOT / "worker" / "reference_text.txt").read_text(encoding="utf-8").strip()
        if not ref.exists():
            raise RuntimeError("Reference WAV is unavailable")
        wave, rate, _ = self.model.infer(ref_file=str(ref), ref_text=ref_text, gen_text=text, nfe_step=32, cfg_strength=2.0, sway_sampling_coef=-1.0, speed=1.0, file_wave=str(output), seed=20260803)
        return rate, len(np.asarray(wave)) / rate


class Silero:
    model = None

    def make(self, text: str, output: Path) -> tuple[int, float]:
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
            audio = self.model.apply_tts(text=sentence, speaker="xenia", sample_rate=rate).detach().cpu().numpy().astype(np.float32)
            chunks.extend((audio, pause))
        wave = np.concatenate(chunks[:-1])
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
        rate, duration = engine.make(accented, output)
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
