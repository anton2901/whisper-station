# Задачи

## Сделано (0.3.0)

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
- [ ] Публикация в AUR (нужны GitHub-remote и аккаунт AUR)

## Далёкое будущее (после доработки под Linux)

- Переносимость: пакеты для Debian/Fedora, Flatpak, X11 (`xclip`/`xdotool`)
- Портал `GlobalShortcuts` для GNOME/Hyprland
- Распространение сервера распознавания (venv/Docker) вместе с моделью
- Матрица тестов на KDE/GNOME/Hyprland

## Известные ограничения

- Хоткей проверен только на KDE Plasma 6.8 (KWin), Wayland.
- Позиция HUD — на усмотрение композитора.
- Восстановление буфера — best effort с задержкой 1.5 с.
