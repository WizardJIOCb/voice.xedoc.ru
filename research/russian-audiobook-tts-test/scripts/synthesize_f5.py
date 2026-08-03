from __future__ import annotations

import argparse
import json
import os
import time
import unicodedata
from pathlib import Path

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[1]
ACUTE = "\u0301"


def combining_to_plus(text: str) -> str:
    output: list[str] = []
    for char in unicodedata.normalize("NFD", text):
        if char == ACUTE and output:
            vowel = output.pop()
            output.extend(("+", vowel))
        elif char == "\u0308":
            if output and output[-1] in ("е", "Е"):
                output[-1] = "ё" if output[-1] == "е" else "Ё"
        else:
            output.append(char)
    return unicodedata.normalize("NFC", "".join(output))


def read_generation_text(mode: str) -> str:
    if mode == "gold":
        path = ROOT / "data" / "gold_text.txt"
    else:
        path = ROOT / "reports" / f"{mode}_output.txt"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return " ".join(combining_to_plus(line) for line in lines[:4])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("gold", "ruaccent", "silero"), default="gold")
    parser.add_argument("--nfe-step", type=int, default=32)
    parser.add_argument("--seed", type=int, default=20260803)
    args = parser.parse_args()

    cache_dir = ROOT / "models" / "hf-cache"
    os.environ["HF_HOME"] = str(cache_dir)
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from f5_tts.api import F5TTS

    checkpoint = (
        ROOT
        / "models"
        / "f5"
        / "F5TTS_v1_Base_v2"
        / "model_last_inference.safetensors"
    )
    vocab = ROOT / "models" / "f5" / "F5TTS_v1_Base" / "vocab.txt"
    reference = ROOT / "outputs" / "silero_v5_5_xenia_reference.wav"
    reference_text = combining_to_plus(
        (ROOT / "data" / "reference_gold.txt").read_text(encoding="utf-8").strip()
    )
    output_dir = ROOT / "outputs"
    report_dir = ROOT / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"f5_russian_v2_xenia_clone_{args.mode}.wav"

    torch.cuda.reset_peak_memory_stats()
    load_started = time.perf_counter()
    model = F5TTS(
        model="F5TTS_v1_Base",
        ckpt_file=str(checkpoint),
        vocab_file=str(vocab),
        device="cuda",
        hf_cache_dir=str(cache_dir),
    )
    load_seconds = time.perf_counter() - load_started

    infer_started = time.perf_counter()
    waveform, sample_rate, _ = model.infer(
        ref_file=str(reference),
        ref_text=reference_text,
        gen_text=read_generation_text(args.mode),
        nfe_step=args.nfe_step,
        cfg_strength=2.0,
        sway_sampling_coef=-1.0,
        speed=1.0,
        cross_fade_duration=0.15,
        remove_silence=False,
        file_wave=str(output_path),
        seed=args.seed,
    )
    infer_seconds = time.perf_counter() - infer_started
    duration = len(np.asarray(waveform)) / sample_rate
    stats = {
        "model": "Misha24-10 F5-TTS Russian F5TTS_v1_Base_v2",
        "voice_reference": str(reference),
        "input": args.mode,
        "sample_rate": sample_rate,
        "duration_seconds": duration,
        "load_seconds": load_seconds,
        "inference_seconds": infer_seconds,
        "realtime_factor": infer_seconds / duration,
        "peak_cuda_gib": torch.cuda.max_memory_allocated() / (1024**3),
        "nfe_step": args.nfe_step,
        "seed": args.seed,
        "output": str(output_path),
    }
    report_dir.joinpath(f"f5_russian_v2_{args.mode}.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

