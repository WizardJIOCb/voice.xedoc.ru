from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
MODELS = ROOT / "models"
ACUTE = "\u0301"
WORD_RE = re.compile(r"[А-Яа-яЁё\u0301]+")


def plus_to_combining(text: str) -> str:
    """Convert Silero/RUAccent's `сл+ово` notation to Unicode U+0301."""
    out: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "+" and index + 1 < len(text):
            stressed = text[index + 1]
            out.append(stressed)
            if stressed.lower() != "ё":
                out.append(ACUTE)
            index += 2
            continue
        out.append(text[index])
        index += 1
    return unicodedata.normalize("NFD", "".join(out))


def plain(word: str) -> str:
    return unicodedata.normalize("NFD", word).replace(ACUTE, "").lower()


def tokens(line: str) -> list[str]:
    return [unicodedata.normalize("NFD", item) for item in WORD_RE.findall(line)]


def run_silero(lines: list[str]) -> tuple[list[str], float, float]:
    from silero_stress import load_accentor

    started = time.perf_counter()
    accentor = load_accentor()
    loaded = time.perf_counter()
    output = [plus_to_combining(accentor(line)) for line in lines]
    return output, loaded - started, time.perf_counter() - loaded


def run_ruaccent(lines: list[str], model_size: str) -> tuple[list[str], float, float]:
    from ruaccent import RUAccent

    workdir = MODELS / "ruaccent"
    workdir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    accentor = RUAccent()
    accentor.load(
        omograph_model_size=model_size,
        use_dictionary=True,
        tiny_mode=False,
        device="CPU",
        workdir=str(workdir),
    )
    loaded = time.perf_counter()
    output = [plus_to_combining(accentor.process_all(line)) for line in lines]
    return output, loaded - started, time.perf_counter() - loaded


def score(name: str, output: list[str], targets: list[dict]) -> dict:
    rows: list[dict] = []
    for target in targets:
        line_index = int(target["line"]) - 1
        word = target["word"]
        found = [item for item in tokens(output[line_index]) if plain(item) == word]
        expected = [unicodedata.normalize("NFD", item) for item in target["expected"]]
        for occurrence, wanted in enumerate(expected):
            actual = found[occurrence] if occurrence < len(found) else "<не найдено>"
            rows.append(
                {
                    "line": line_index + 1,
                    "word": word,
                    "occurrence": occurrence + 1,
                    "expected": unicodedata.normalize("NFC", wanted),
                    "actual": unicodedata.normalize("NFC", actual),
                    "correct": actual == wanted,
                }
            )
    correct = sum(row["correct"] for row in rows)
    return {
        "model": name,
        "correct": correct,
        "total": len(rows),
        "accuracy": correct / len(rows) if rows else 0.0,
        "rows": rows,
    }


def markdown(results: list[dict]) -> str:
    lines = ["# Контекстные ударения", ""]
    lines.append("| Модель | Верно | Точность | Загрузка | Обработка |")
    lines.append("|---|---:|---:|---:|---:|")
    for result in results:
        lines.append(
            f"| {result['model']} | {result['correct']}/{result['total']} | "
            f"{result['accuracy']:.1%} | {result['load_seconds']:.2f} с | "
            f"{result['process_seconds']:.2f} с |"
        )
    for result in results:
        lines.extend(["", f"## {result['model']}", ""])
        lines.append("| Строка | Слово | Эталон | Модель | |")
        lines.append("|---:|---|---|---|:---:|")
        for row in result["rows"]:
            mark = "✅" if row["correct"] else "❌"
            lines.append(
                f"| {row['line']} | {row['word']} | {row['expected']} | "
                f"{row['actual']} | {mark} |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--models",
        nargs="+",
        choices=("silero", "ruaccent"),
        default=("silero", "ruaccent"),
    )
    parser.add_argument("--ruaccent-size", default="turbo3.1")
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    source_lines = DATA.joinpath("test_text.txt").read_text(encoding="utf-8").splitlines()
    targets = json.loads(DATA.joinpath("targets.json").read_text(encoding="utf-8"))
    results: list[dict] = []

    for model_name in args.models:
        if model_name == "silero":
            output, load_seconds, process_seconds = run_silero(source_lines)
            label = "Silero Stress 1.4"
        else:
            output, load_seconds, process_seconds = run_ruaccent(
                source_lines, args.ruaccent_size
            )
            label = f"RUAccent {args.ruaccent_size}"

        REPORTS.joinpath(f"{model_name}_output.txt").write_text(
            "\n".join(unicodedata.normalize("NFC", line) for line in output) + "\n",
            encoding="utf-8",
        )
        result = score(label, output, targets)
        result["load_seconds"] = load_seconds
        result["process_seconds"] = process_seconds
        results.append(result)

    REPORTS.joinpath("accent_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    REPORTS.joinpath("accent_results.md").write_text(markdown(results), encoding="utf-8")
    print(markdown(results))


if __name__ == "__main__":
    main()
