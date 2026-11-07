"""Глобальный хоткей через org.kde.kglobalaccel (KDE Plasma 6, Wayland).

Почему dbus-python, а не QtDBus: PySide6 не умеет маршаллить `ai`/`a(ai)`,
а именно такие подписи у setShortcutKeys. Вся работа с шиной идёт в отдельном
потоке, наружу — только колбэк активации.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import APP_NAME, APP_TITLE

log = logging.getLogger(__name__)

SERVICE = "org.kde.kglobalaccel"
OBJECT_PATH = "/kglobalaccel"
INTERFACE = "org.kde.KGlobalAccel"
COMPONENT_INTERFACE = "org.kde.kglobalaccel.Component"

# KGlobalAccelPrivate::SetShortcutFlags
SET_PRESENT = 0x1
IS_DEFAULT = 0x2
NO_AUTOLOADING = 0x4

DEBOUNCE_SECONDS = 0.15


class HotkeyError(RuntimeError):
    """Хоткей зарегистрировать не удалось."""


@dataclass(frozen=True)
class ActionId:
    component: str
    action: str
    friendly: str
    action_text: str

    def as_list(self) -> list[str]:
        """Ровно тот порядок, который ждёт kglobalaccel (4 поля)."""
        return [self.component, self.action, self.friendly, self.action_text]


def shortcut_to_int(sequence: str) -> int:
    """'Meta+Alt+D' -> комбинированный код Qt (402653252)."""
    from PySide6.QtGui import QKeySequence

    seq = QKeySequence(sequence)
    # Qt молча превращает мусор в Key_unknown и пустую строку.
    if not seq.count() or not seq.toString():
        raise HotkeyError(f"Не разобрал комбинацию клавиш: {sequence!r}")
    combined = int(seq[0].toCombined())
    if combined <= 0:
        raise HotkeyError(f"Пустая комбинация клавиш: {sequence!r}")
    return combined


def int_to_shortcut(value: int) -> str:
    from PySide6.QtGui import QKeySequence

    return QKeySequence(value).toString()


def kglobalaccel_available() -> bool:
    try:
        import dbus

        # private=True: не трогаем общее соединение основного потока
        bus = dbus.SessionBus(private=True)
    except Exception:  # noqa: BLE001 - диагностика
        return False
    try:
        return bool(bus.name_has_owner(SERVICE))
    except Exception:  # noqa: BLE001
        return False


def _first_key(shortcut_keys: object) -> int | None:
    """Достать первый ненулевой код из ответа a(ai)."""
    try:
        for entry in shortcut_keys:  # type: ignore[union-attr]
            for inner in entry:
                sequence = list(inner)
                for value in sequence:
                    if int(value) > 0:
                        return int(value)
    except (TypeError, ValueError):
        return None
    return None


class GlobalHotkey:
    """Регистрация хоткея и ожидание активации в фоновом потоке."""

    def __init__(
        self,
        on_activate: Callable[[], None],
        *,
        component: str = APP_NAME,
        friendly: str = APP_TITLE,
        action: str = "toggle",
        action_text: str = "Диктовка",
    ) -> None:
        self.action_id = ActionId(component, action, friendly, action_text)
        self._on_activate = on_activate
        self._thread: threading.Thread | None = None
        self._loop: object | None = None
        self._ready = threading.Event()
        self._error: HotkeyError | None = None
        self._effective: str | None = None
        self._last_fire = 0.0

    # --- публичное API --------------------------------------------------
    @property
    def active(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, sequence: str, *, force: bool = False, timeout: float = 8.0) -> str:
        """Зарегистрировать хоткей. Возвращает фактическую комбинацию.

        force=False — уважаем значение, сохранённое в kglobalshortcutsrc
        (пользователь мог поменять его в System Settings).
        force=True — применить нашу комбинацию (кнопка «Применить» в настройках).
        """
        self.stop()
        self._ready.clear()
        self._error = None
        self._effective = None
        self._thread = threading.Thread(
            target=self._run, args=(sequence, force), name="whisper-hotkey", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            self._error = HotkeyError("kglobalaccel не ответил за %.0f с" % timeout)
            raise self._error
        if self._error is not None:
            raise self._error
        return self._effective or sequence

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        loop = self._loop
        try:
            if loop is not None:
                from gi.repository import GLib

                GLib.idle_add(loop.quit)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - выключение не должно падать
            log.debug("hotkey: не смог остановить GLib-цикл", exc_info=True)
        thread.join(timeout=3.0)
        self._thread = None
        self._loop = None

    # --- поток ----------------------------------------------------------
    def _run(self, sequence: str, force: bool) -> None:
        try:
            import dbus
            from dbus.mainloop.glib import DBusGMainLoop
            from gi.repository import GLib
        except Exception as exc:  # noqa: BLE001 - сообщаем наверх
            self._error = HotkeyError(f"Нет python-dbus/PyGObject: {exc}")
            self._ready.set()
            return

        DBusGMainLoop(set_as_default=True)
        daemon = None
        bus = None
        try:
            bus = dbus.SessionBus(private=True)
            loop = GLib.MainLoop()
            self._loop = loop

            bus.add_signal_receiver(
                self._on_signal_pressed,
                signal_name="globalShortcutPressed",
                dbus_interface=COMPONENT_INTERFACE,
                bus_name=SERVICE,
            )
            bus.add_signal_receiver(
                self._on_signal_pressed,
                signal_name="pressed",
                dbus_interface=COMPONENT_INTERFACE,
                bus_name=SERVICE,
            )

            key = shortcut_to_int(sequence)
            action_list = dbus.Array(self.action_id.as_list(), signature="s")
            keys = dbus.Array(
                [dbus.Struct([dbus.Array([key], signature="i")], signature="ai")],
                signature="(ai)",
            )
            flags = SET_PRESENT | IS_DEFAULT | (NO_AUTOLOADING if force else 0)

            daemon = dbus.Interface(bus.get_object(SERVICE, OBJECT_PATH), INTERFACE)
            daemon.doRegister(action_list)
            daemon.setShortcutKeys(action_list, keys, dbus.UInt32(flags))
            granted = daemon.shortcutKeys(action_list)
            effective = _first_key(granted)
            if effective is None:
                self._error = HotkeyError(
                    f"Комбинация {sequence} занята другим приложением — назначьте другую"
                )
                self._ready.set()
                return
            if int(effective) != key:
                log.warning(
                    "hotkey: kglobalaccel вернул %s вместо %s",
                    int_to_shortcut(effective),
                    sequence,
                )
            self._effective = int_to_shortcut(effective)
            log.info("hotkey: зарегистрирован %s", self._effective)
            self._ready.set()
            loop.run()
        except Exception as exc:  # noqa: BLE001 - любая ошибка шины = нет хоткея
            if not self._ready.is_set():
                self._error = HotkeyError(f"Не удалось зарегистрировать хоткей: {exc}")
                self._ready.set()
            else:
                log.warning("hotkey: поток завершился с ошибкой: %s", exc)
        finally:
            # Компонент намеренно не снимаем с регистрации: при перезапуске
            # старый процесс успевает удалить запись нового, и хоткей «умирает».
            # Запись в kglobalshortcutsrc остаётся, как у обычных KDE-приложений.
            if bus is not None:
                try:
                    bus.close()
                except Exception:  # noqa: BLE001
                    pass

    def _on_signal_pressed(self, *args: object) -> None:
        """Сигналы: globalShortcutPressed(component, action, ts) или pressed(actionId, opts)."""
        if len(args) >= 2:
            action = args[1] if len(args) > 2 else args[0]
            component = args[0] if len(args) > 2 else None
            if component is not None and str(component) != self.action_id.component:
                return
            if str(action) != self.action_id.action:
                return
        now = time.monotonic()
        if now - self._last_fire < DEBOUNCE_SECONDS:
            return
        self._last_fire = now
        log.debug("hotkey: активация")
        try:
            self._on_activate()
        except Exception:  # noqa: BLE001 - колбэк не должен убивать поток шины
            log.exception("hotkey: колбэк активации упал")
