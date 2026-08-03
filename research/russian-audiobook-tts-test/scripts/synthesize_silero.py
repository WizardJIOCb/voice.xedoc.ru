from __future__ import annotations

import argparse
import json
import time
import unicodedata
from pathlib import Path

import numpy as np
import soundfile as sf
import torch


ROOT = Path(__file__).resolve().parents[1]
ACUTE = "\u0301"


def combining_to_plus(text: str) -> str:
    chars = list(unicodedata.normalize("NFD", text))
    output: list[str] = []
    for char in chars:
        if char == ACUTE and output:
            vowel = output.pop()
            output.extend(("+", vowel))
        elif char != "\u0308":
            output.append(char)
        else:
            # Recompose е + diaeresis back to ё, which is inherently stressed.
            if output and output[-1] in ("е", "Е"):
                output[-1] = "ё" if output[-1] == "е" else "Ё"
    return unicodedata.normalize("NFC", "".join(output))


def load_lines(mode: str) -> list[str]:
    if mode == "auto":
        path = ROOT / "data" / "synthesis_text.txt"
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if mode == "reference":
        path = ROOT / "data" / "reference_gold.txt"
    elif mode == "gold":
        path = ROOT / "data" / "gold_text.txt"
    else:
        path = ROOT / "reports" / f"{mode}_output.txt"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [combining_to_plus(line) for line in lines[:4]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("auto", "gold", "silero", "ruaccent", "reference"),
        default="auto",
    )
    parser.add_argument("--speaker", default="xenia")
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()

    model_path = ROOT / "models" / "silero" / "v5_5_ru.pt"
    output_dir = ROOT / "outputs"
    report_dir = ROOT / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    torch.set_num_threads(args.threads)
    started = time.perf_counter()
    model = torch.package.PackageImporter(str(model_path)).load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))
    load_seconds = time.perf_counter() - started

    chunks: list[np.ndarray] = []
    pause = np.zeros(round(args.sample_rate * 0.42), dtype=np.float32)
    lines = load_lines(args.mode)
    infer_started = time.perf_counter()
    for line in lines:
        audio = model.apply_tts(
            text=line,
            speaker=args.speaker,
            sample_rate=args.sample_rate,
        )
        chunks.extend((audio.detach().cpu().numpy().astype(np.float32), pause))
    infer_seconds = time.perf_counter() - infer_started

    waveform = np.concatenate(chunks[:-1])
    peak = float(np.max(np.abs(waveform)))
    if peak > 0:
        waveform *= 0.92 / peak
    output_path = output_dir / f"silero_v5_5_{args.speaker}_{args.mode}.wav"
    sf.write(output_path, waveform, args.sample_rate, subtype="PCM_16")

    stats = {
        "model": "Silero TTS v5_5_ru",
        "speaker": args.speaker,
        "input": args.mode,
        "sample_rate": args.sample_rate,
        "duration_seconds": len(waveform) / args.sample_rate,
        "load_seconds": load_seconds,
        "inference_seconds": infer_seconds,
        "realtime_factor": infer_seconds / (len(waveform) / args.sample_rate),
        "output": str(output_path),
    }
    report_dir.joinpath(f"silero_{args.speaker}_{args.mode}.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
