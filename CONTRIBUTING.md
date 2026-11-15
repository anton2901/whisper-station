# Contributing

[English](CONTRIBUTING.md) | [Русский](CONTRIBUTING.ru.md)

The project is small: fork, branch, pull request. Before a PR run
`make lint && make test` — red tests are not merged.

## Stack and rules

- Python 3.12+, PySide6, `dbus-python`, PyGObject. New dependencies only with the
  maintainer's agreement: the standard library is preferred.
- Code, names and **commits** in English; documentation, README and interface texts in
  Russian (English README is the GitHub landing page).
- `print()` only in `cli.py` and `app.py`, otherwise `logging`.
- Network only to `127.0.0.1` (the server address is checked in `config.is_loopback_url`).
- Do not touch `.whisper-local/**`: it is a foreign service, reuse only.
- Tests live in `tests/`; do not create them next to the code.

## Run and check

```sh
make run        # daemon from the repository
make test       # unittest, no external packages
make lint       # mini-linter (syntax, line length, imports, print)
make doctor     # environment: hotkey, insertion, server, model
```

Verify behaviour on a live KDE session: hotkey, HUD, Esc, insertion into a normal window
and into a terminal.

## What to attach to an issue

- `whisper-station doctor` (full output);
- `whisper-station server status`;
- the tail of `~/.local/state/whisper-station/app.log`;
- versions: `whisper-station --version`, distribution, Plasma/Wayland version.

## Where to add what

| Task | File |
|---|---|
| a new model in the catalog | `whisper_station/catalog.py` (name, HF repository, size) |
| a new setting | `whisper_station/config.py` (field + `SECTIONS` + `COMMENTS` + validation) |
| insertion behaviour | `whisper_station/inject.py` + `tests/test_inject.py` |
| server/endpoints | `whisper_station/server/` + `tests/test_server.py` |
| documentation | `docs/`, one screen per document |
