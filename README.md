# whisper-dictate

Локальная диктовка для KDE Plasma 6 / Wayland: глобальный хоткей → запись микрофона →
распознавание локальной моделью Whisper → текст в активном окне. Без облака и телеметрии:
сеть только на `127.0.0.1`.

## Что нужно

Проверено на CachyOS (Arch-based), KDE Plasma 6.8, Wayland:

- Python 3.12+ с `PySide6`, `dbus-python`, `PyGObject` (`pyside6 python-dbus python-gobject`);
- `pipewire` (`pw-record`; `parec` — запасной вариант), `wl-clipboard`, `libnotify`;
- сервер распознавания на `127.0.0.1:8765` (OpenAI-совместимый, faster-whisper);
- `ydotool` и доступ к `/dev/uinput` — для вставки через Ctrl+V (на CachyOS ACL уже есть).

Готовность проверить одной командой: `bin/whisper-dictate doctor`.

## Запуск из репозитория

```sh
make test        # юнит-тесты (unittest, без внешних пакетов)
make lint        # мини-линтер (синтаксис, стиль, импорты)
make run         # демон с иконкой в трее (передний план)
make doctor      # проверка окружения: хоткей, вставка, сервер
```

Второй экземпляр не запускается: демон держит UNIX-сокет в `$XDG_RUNTIME_DIR`.

## Установка пакетом

```sh
makepkg -f                       # собрать (зависимости должны стоять)
sudo pacman -U whisper-dictate-0.1.0-1-any.pkg.tar.zst
```

Пакет кладёт код в `/usr/lib/whisper-dictate`, обёртку — в `/usr/bin/whisper-dictate`,
`.desktop` и иконку — в `/usr/share`. После установки:

```sh
whisper-dictate                    # запустить демон (трей)
whisper-dictate autostart on       # автозапуск при входе
```

Автозапуск пишет `~/.config/autostart/whisper-dictate.desktop`
(`Exec=/usr/bin/whisper-dictate daemon`).

## Как пользоваться

1. Запустите `whisper-dictate` (трей) — или включите автозапуск в настройках.
2. Нажмите `Meta+Alt+D`, говорите, нажмите ещё раз. Появится компактный HUD
   с осциллограммой голоса и таймером.
3. Текст распознаётся и вставляется в активное окно (буфер + Ctrl+V).
4. `Esc` в HUD — отмена без вставки; кнопки «Стоп»/«Отмена» делают то же самое.

Если сервер не запущен, приложение поднимет его само (`run.sh` из `.whisper-local`
находится автоматически) и дождётся `/health`. Чужой сервер не убивается.

## Настройки

`~/.config/whisper-dictate/config.toml` или окно «Настройки…» в трее: хоткей, язык,
адрес и команда сервера, способ вставки (`paste`/`type`/`clipboard`), восстановление
буфера, автозапуск, звуковой сигнал, длительности записи.

Хоткей также виден в System Settings → Shortcuts → Whisper Dictate: менять можно там.
Резервный вариант для любой сессии — назначить сочетание на команду `whisper-dictate toggle`.

## Команды

`toggle`, `start`, `stop`, `cancel`, `settings`, `status`, `transcribe FILE`,
`doctor`, `config`, `log`, `autostart on|off`, `service status|start`, `quit`, `daemon`.

## Ограничения Wayland (честно)

- Хоткей работает через `org.kde.kglobalaccel` — проверено на Plasma 6.8 (KWin).
  XDG-портал `GlobalShortcuts` не используется.
- HUD на время записи забирает фокус (KWin не даёт клавиатуру окну без фокуса, иначе
  не работают Esc и кнопки). Перед вставкой HUD прячется, фокус возвращается в окно.
- Позиция HUD задаётся правилом KWin «Whisper Dictate HUD» (верх экрана по центру):
  Wayland не позволяет клиенту двигать окна. Правило видно и удаляется в
  System Settings → Window Rules; отключается галочкой в настройках приложения.
- Запись идёт через `pw-record`: `parec` на PipeWire не отдаёт данные, если stdout — pipe
  (в файл пишет нормально), поэтому он оставлен только как запасной вариант.
- Короткое нажатие хоткея (меньше 0.25 с) и тишина не считаются ошибкой и не показывают
  уведомлений — только реальные сбои. Запись ниже порога тишины не отправляется в модель,
  а типовые «субтитры/музыка» от Whisper отфильтровываются.
- Восстановление буфера отложено на 1.5 с: Wayland отдаёт данные вставки асинхронно.
- Трей — StatusNotifierItem средствами Qt; на KDE работает без `libayatana-appindicator`.

## Удаление

```sh
sudo pacman -R whisper-dictate
rm -rf ~/.config/whisper-dictate ~/.local/state/whisper-dictate
```

Архитектура и решения — `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, проверки — `docs/VERIFICATION.md`.
