# AGENTS.md

## Команды

```sh
make test     # python3 -m unittest discover -s tests -t .
make lint     # python3 tools/check.py
make run      # PYTHONPATH=. python3 -m whisper_dictate
make doctor   # бинарь из bin/ + проверка окружения
makepkg -f    # сборка пакета (без установки)
```

`bin/whisper-dictate <команда>` — то же, что `make run`, но с аргументами CLI.

## Структура

- `whisper_dictate/` — код: `cli.py` (CLI), `app.py` (трей, IPC), `controller.py`
  (состояния), `recorder.py`, `stt.py`, `inject.py`, `hotkey.py`, `service.py`,
  `hud.py`, `settings_ui.py`, `config.py`.
- `tests/` — unittest, по файлу на модуль. Тесты рядом с кодом не создаём.
- `packaging/` — `.desktop` и SVG-иконка; `PKGBUILD` — в корне.
- `docs/` — архитектура, решения, задачи; каждый документ ≤ 1 экрана.

## Правила

- Стек: Python 3.12+, PySide6 (Qt6), dbus-python, PyGObject. Новые зависимости — только
  после согласия пользователя. Стандартная библиотека предпочтительнее.
- Код, имена и коммиты — по-английски; документация — по-русски.
- `print()` допустим только в `cli.py` и `app.py`; иначе `logging`.
- Никаких сетевых вызовов вне `127.0.0.1`; адрес сервера проверяется в `config.py`.
- Не менять `.whisper-local/**` (это общий сервис DSH) и не убивать чужой сервер.
- `ydotoold` запускается от пользователя; права, группы и `uinput` не настраивать.
- Перед PR/коммитом: `make lint && make test`. Красные тесты не коммитить.
- Конфиг — только через `config.py`; путь `~/.config/whisper-dictate/config.toml`.
