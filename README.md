# voice.xedoc.ru

Веб-интерфейс русской озвучки: сервер хранит очередь и готовые аудиофайлы, а
worker на Windows с RTX 4070 Ti выполняет RUAccent и синтез локально.

```text
Браузер → voice.xedoc.ru → очередь на 82.146.42.213
                                 ↑       ↓
                   Windows GPU worker: RUAccent → F5 / Silero → WAV
```

Worker сам подключается к серверу по HTTPS, поэтому на Windows не открывается
публичный порт.

## Первый запуск worker’а

```powershell
.\scripts\import-models.ps1
.\scripts\bootstrap-worker.ps1
.\scripts\start-worker.ps1
```

For a regular launch on this computer, double-click `start.bat` in the project
root. It will prepare the local worker on its first run and then start it.

Секреты worker’а лежат в `.runtime/` и не попадают в Git. Лог:
`.runtime/worker.log`.

## Лицензии

F5 Russian v2 и русский Silero v5.5, использованные здесь, имеют
некоммерческие лицензии. Перед коммерческим выпуском аудиокниг нужно получить
разрешение либо заменить чекпойнты.
