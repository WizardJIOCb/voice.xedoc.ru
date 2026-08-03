# Локальный тест русской озвучки книг

Воспроизводимый A/B-тест двух отдельных этапов:

1. постановка ударений с учётом контекста (`Silero Stress`, `RUAccent`);
2. синтез речи (`Silero TTS v5_5_ru`, русская адаптация `F5-TTS v2`;
   `Chatterbox Multilingual V3` оставлен как экспериментальный вариант).

Все окружения и веса моделей хранятся внутри этой папки. Исходный тестовый
фрагмент написан специально для проверки и не содержит чужого защищённого текста.

## Структура

- `data/` — исходный текст, эталон и перечень проверяемых слов;
- `scripts/` — установка, тест ударений и синтез;
- `reports/` — машинные и читаемые результаты;
- `outputs/` — WAV-файлы;
- `models/` — локальный кэш весов.

## Повторный запуск

```powershell
uv venv --python 3.11 .venv-accent
uv pip install --python .venv-accent\Scripts\python.exe -r requirements-accent.txt
.venv-accent\Scripts\python.exe scripts\benchmark_accents.py --models silero ruaccent
.venv-accent\Scripts\python.exe scripts\score_outputs.py
```

Для F5 сначала ставится CUDA-сборка PyTorch, затем остальные зависимости:

```powershell
uv venv --python 3.11 .venv-f5
uv pip install --python .venv-f5\Scripts\python.exe torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --index-url https://download.pytorch.org/whl/cu128
uv pip install --python .venv-f5\Scripts\python.exe -r requirements-f5.txt
.venv-f5\Scripts\python.exe scripts\synthesize_f5.py --mode ruaccent
```

Silero TTS запускается из `.venv-speech`:

```powershell
.venv-speech\Scripts\python.exe scripts\synthesize_silero.py --mode ruaccent --speaker xenia
```

Полный результат текущего прогона — в `RESULTS.md`.
