# Задачи

## Сделано (0.4.0, 2026-11-15)

- [x] Встроенный сервер распознавания `whisper_station/server/`: `/health`, `/v1/models`,
      `/v1/audio/transcriptions` на стандартной библиотеке, `prompt`, `verbose_json`
- [x] `server install|status|start|uninstall`: venv с faster-whisper в `~/.local/share`
- [x] `[model]` в конфиге, группа «Модель распознавания» в настройках, перезапуск сервера
- [x] Каталог из шести моделей, скачивание в каталог сервера, проверка места, отмена
- [x] Словарь уходит в модель как `initial_prompt` (до 20 терминов)
- [x] `doctor`: окружение и модель; `service.plan()` без пути DSH
- [x] CI (Arch-контейнер) и версия 0.4.0

## Сделано (0.3.0–0.3.1)

- [x] Каркас: структура, конфиг TOML, пути XDG, логирование, PKGBUILD, `.desktop`, иконка
- [x] Запись: `parec`/`pw-record` → WAV 16 кГц моно, индикатор уровня, отмена
- [x] Распознавание: multipart-клиент, таймауты, ретрай, понятные ошибки
- [x] Вставка: буфер + Ctrl+V, свой `ydotoold`, восстановление буфера, режимы `type`/`clipboard`
- [x] Хоткей: `org.kde.kglobalaccel`, сохранение в System Settings, повторная регистрация
- [x] Сервис: `/health`, запуск `run.sh`, чужой сервер не трогаем, свой гасим при выходе
- [x] UI: трей с меню и состоянием, HUD с таймером/уровнем/Esc, окно настроек
- [x] CLI: `toggle/start/stop/cancel/settings/status/transcribe/doctor/config/log/autostart/service/quit`
- [x] Тесты (70) и мини-линтер; проверка на живой сессии (см. `VERIFICATION.md`)

## Ближайшее

- [x] Push-to-talk (удержание хоткея) — режим `press`, проверен на KWin
- [ ] Резервный путь хоткея через `org.freedesktop.portal.GlobalShortcuts` для не-KDE сессий
- [x] HUD сверху по центру — правилом KWin (wlr-layer-shell KWin не поддерживает)
- [x] Компактный HUD (300×68) с осциллограммой вместо полоски уровня
- [x] Запись через `pw-record --raw`: `parec` молчит в pipe, а без `--raw` идёт AU/float32
- [x] Установка пакетом в `/usr/lib/whisper-station` и автозапуск при входе
- [x] Схема архитектуры (Archify, showcase) в `.archify/` с проверенными гейтами
- [x] Вставка в терминалы: настраиваемое сочетание Ctrl+V / Ctrl+Shift+V, безопасный буфер
- [x] Падение при сохранении настроек (SIGSEGV в libdbus) — исправлено
- [x] Звуковые сигналы через `libcanberra` вместо `QApplication.beep()`
- [x] Команда `whisper-station model download` с явным подтверждением
- [x] `systemd --user` юнит как альтернатива autostart
- [x] Ретрай записи и пункт трея «Вставить последний текст»
- [x] Лицензия GPL-3.0
- [x] Переименование в whisper-station, новые иконки и HUD «Станция»
- [x] Живой предпросмотр распознавания в HUD (бегущая строка, включён по умолчанию)
- [x] Предел записи 30 минут и таймаут распознавания под длительность (0.3.1)
- [x] Герметичные тесты вставки: подставной ydotoold-сокет в tempdir, без `/run/user`
- [ ] Публикация в AUR (нужны GitHub-remote и аккаунт AUR)

## План разработки

Детальный план итераций, критерии приёмки и порядок работ — [ROADMAP.md](ROADMAP.md).
Обоснование ближайших итераций — [HANDY-ANALYSIS.md](HANDY-ANALYSIS.md).

### Сейчас: 0.4.1 «Текст, режимы и вставка»

- [ ] Hybrid-режим хоткея: тап фиксирует, удержание > порога — PTT
- [ ] `hold_threshold_ms` в конфиге и настройках
- [x] Словарь терминов с нечёткой коррекцией (`textproc.py`)
- [x] Удаление филлеров и повторов, `trailing_space`
- [x] Словарь в модель как `initial_prompt` (0.4.0)
- [ ] Задержки вставки, auto-submit (off по умолчанию), блокировка вставок
- [ ] Probe синтаксиса ydotool (raw/symbolic)
- [ ] Hook `hooks/transcription` (stdin → stdout, fail-open)
- [ ] Быстрое переключение языка в трее
- [ ] Публикация: AUR, `.gitignore` пакета, README со скриншотами

## Публикация (CachyOS-only)

- [x] Версия 0.4.0 в `pyproject.toml`, `PKGBUILD`, `__init__.py`; запись в `CHANGELOG.md`
- [x] `tests/test_version.py` ловит расхождение версий и отсутствие раздела в CHANGELOG
- [x] CI: Arch-контейнер, `make lint && make test`, `makepkg -f --nocheck`
- [x] Сборка из чистого `git archive`: пакет и `whisper-station 0.4.0`
- [x] Проверка установленного дерева пакета: свой сервер поднимается, текст распознаётся
- [x] `install.sh`: установка одной командой (`--dry-run`, `--cpu`, `--model`, `--no-autostart`)
- [x] `CONTRIBUTING.md` и `docs/RELEASE.md` (порядок публикации, тег, архив, AUR)
- [x] README на английском (`README.md`) и русском (`README.ru.md`), CONTRIBUTING так же
- [x] Скриншоты HUD и окна настроек (`tools/screenshots.py`), починена ширина настроек
- [x] README: статус (CachyOS/KDE), зависимости, сервер и модели, ограничения
- [ ] Заполнить `url` в PKGBUILD адресом репозитория
- [ ] **Чистая проверка:** снести пакет/сервер/конфиг, поставить `./install.sh`, проверить вживую
- [ ] Создать репозиторий на GitHub, `git push`, тег `v0.4.0`, релиз с архивом и пакетом
- [ ] AUR — отдельным шагом (`.SRCINFO`, `source` из архива релиза)
- [ ] Английская версия README — по желанию, не блокирует релиз

### Дальше

- [ ] 0.4.2 «Надёжность»: HUD timer, ротация лога, миграции конфига, doctor,
      cancel-хоткей
- [ ] 0.5.0 «История и настройки»: SQLite-история, микрофон, вкладки
- [ ] 0.6.0 «Портируемость»: fallback инструментов, файлы, портал хоткея

## Далёкое будущее (после доработки под Linux)

- Переносимость: пакеты для Debian/Fedora, Flatpak, X11 (`xclip`/`xdotool`)
- Портал `GlobalShortcuts` для GNOME/Hyprland
- Распространение сервера распознавания (venv/Docker) вместе с моделью
- Матрица тестов на KDE/GNOME/Hyprland

## Известные ограничения

- Хоткей проверен только на KDE Plasma 6.8 (KWin), Wayland.
- Позиция HUD — на усмотрение композитора.
- Восстановление буфера — best effort с задержкой 1.5 с.
- Словарь — только пост-коррекция: сервер игнорирует `prompt`/`hotwords`.
  Model-level словарь — отдельная задача к владельцу `.whisper-local`.
