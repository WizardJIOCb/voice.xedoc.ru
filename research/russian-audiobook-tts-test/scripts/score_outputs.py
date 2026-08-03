from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
ACUTE = "\u0301"
VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"
WORD_RE = re.compile(r"[А-Яа-яЁё\u0301]+")


def word_signature(word: str) -> tuple[str, tuple[int, ...], int, tuple[int, ...]]:
    base: list[str] = []
    stresses: list[int] = []
    yo_positions: list[int] = []
    vowel_index = -1
    for char in unicodedata.normalize("NFC", word):
        if char in VOWELS:
            vowel_index += 1
            if char.lower() == "ё":
                stresses.append(vowel_index)
                yo_positions.append(len(base))
            base.append(char.lower().replace("ё", "е"))
        elif char == ACUTE:
            if vowel_index >= 0:
                stresses.append(vowel_index)
        elif "а" <= char.lower() <= "я":
            base.append(char.lower())
    return "".join(base), tuple(sorted(set(stresses))), vowel_index + 1, tuple(yo_positions)


def line_tokens(text: str) -> list[list[str]]:
    return [WORD_RE.findall(line) for line in text.splitlines()]


def metrics(output_path: Path, target_words: set[str]) -> dict:
    gold_lines = line_tokens(DATA.joinpath("gold_text.txt").read_text(encoding="utf-8"))
    actual_lines = line_tokens(output_path.read_text(encoding="utf-8"))
    eligible = correct = covered = yo_total = yo_correct = changed = 0
    errors: list[dict] = []

    for line_no, (gold, actual) in enumerate(zip(gold_lines, actual_lines), start=1):
        if len(gold) != len(actual):
            changed += abs(len(gold) - len(actual))
        for gold_word, actual_word in zip(gold, actual):
            gold_base, gold_stress, vowels, gold_yo = word_signature(gold_word)
            actual_base, actual_stress, _, actual_yo = word_signature(actual_word)
            if gold_base != actual_base:
                changed += 1
                continue
            if gold_yo:
                yo_total += 1
                yo_correct += actual_yo == gold_yo
            if vowels < 2 or gold_base in target_words:
                continue
            eligible += 1
            covered += len(actual_stress) == 1
            is_correct = actual_stress == gold_stress
            correct += is_correct
            if not is_correct:
                errors.append(
                    {
                        "line": line_no,
                        "word": gold_word,
                        "actual": actual_word,
                    }
                )

    return {
        "model": output_path.stem.replace("_output", ""),
        "ordinary_polysyllables_correct": correct,
        "ordinary_polysyllables_total": eligible,
        "ordinary_polysyllables_accuracy": correct / eligible if eligible else 0,
        "ordinary_polysyllables_coverage": covered / eligible if eligible else 0,
        "yo_correct": yo_correct,
        "yo_total": yo_total,
        "changed_or_missing_words": changed,
        "errors": errors,
    }


def main() -> None:
    target_words = {
        item["word"]
        for item in json.loads(DATA.joinpath("targets.json").read_text(encoding="utf-8"))
    }
    results = [
        metrics(REPORTS / "silero_output.txt", target_words),
        metrics(REPORTS / "ruaccent_output.txt", target_words),
    ]
    REPORTS.joinpath("lexical_metrics.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rows = [
        "# Обычные многосложные слова (без целевых омографов)",
        "",
        "| Модель | Верно | Точность | Coverage | `ё` | Изменено слов |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        rows.append(
            f"| {result['model']} | {result['ordinary_polysyllables_correct']}/"
            f"{result['ordinary_polysyllables_total']} | "
            f"{result['ordinary_polysyllables_accuracy']:.1%} | "
            f"{result['ordinary_polysyllables_coverage']:.1%} | "
            f"{result['yo_correct']}/{result['yo_total']} | "
            f"{result['changed_or_missing_words']} |"
        )
    REPORTS.joinpath("lexical_metrics.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("\n".join(rows))


if __name__ == "__main__":
    main()

