# Задачи

## Сделано (0.1.0)

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

- [ ] Push-to-talk (удержание хоткея) — нужен `globalShortcutReleased`, проверить на KWin
- [ ] Резервный путь хоткея через `org.freedesktop.portal.GlobalShortcuts` для не-KDE сессий
- [ ] HUD через `gtk4-layer-shell`/LayerShellQt — если появится в репозиториях
- [ ] Звуковые сигналы через `libcanberra` вместо `QApplication.beep()`
- [ ] Команда `whisper-dictate model download` с явным подтверждением
- [ ] `systemd --user` юнит как альтернатива autostart
- [ ] Лицензия и публикация в AUR

## Известные ограничения

- Хоткей проверен только на KDE Plasma 6.8 (KWin), Wayland.
- Позиция HUD — на усмотрение композитора.
- Восстановление буфера — best effort с задержкой 1.5 с.
