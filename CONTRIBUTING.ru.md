# Участие в проекте

[English](CONTRIBUTING.md) | [Русский](CONTRIBUTING.ru.md)

Проект маленький: проще всего — форк, ветка, pull request.
Перед PR обязательно `make lint && make test` (красные тесты не мержим).

## Стек и правила

- Python 3.12+, PySide6, `dbus-python`, PyGObject. Новые зависимости — только после
  согласия мейнтейнера: стандартная библиотека предпочтительнее.
- Код, имена и **коммиты** — по-английски; документация, README и тексты интерфейса — по-русски.
- `print()` только в `cli.py` и `app.py`, иначе `logging`.
- Сеть — только на `127.0.0.1` (адрес сервера проверяется в `config.is_loopback_url`).
- `.whisper-local/**` не трогаем: это чужой сервис, его можно только переиспользовать.
- Тесты лежат в `tests/`, рядом с кодом их не создаём.

## Как запустить и проверить

```sh
make run        # демон из репозитория
make test       # unittest, без внешних пакетов
make lint       # мини-линтер (синтаксис, длина строк, импорты, print)
make doctor     # окружение: хоткей, вставка, сервер, модель
```

Ветку проверяем на живой KDE-сессии: хоткей, HUD, Esc, вставка в обычное окно и терминал.

## Что приложить к issue

- `whisper-station doctor` (весь вывод);
- `whisper-station server status`;
- хвост `~/.local/state/whisper-station/app.log`;
- версия: `whisper-station --version`, дистрибутив, версия Plasma/Wayland.

## Куда что добавлять

| Задача | Файл |
|---|---|
| новая модель в каталог | `whisper_station/catalog.py` (имя, репозиторий HF, размер) |
| новая настройка | `whisper_station/config.py` (поле + `SECTIONS` + `COMMENTS` + валидация) |
| поведение при вставке | `whisper_station/inject.py` + тесты в `tests/test_inject.py` |
| сервер/эндпоинты | `whisper_station/server/` + `tests/test_server.py` |
| документация | `docs/`, один экран на документ |
