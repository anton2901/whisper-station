"""Глобальный хоткей через org.kde.kglobalaccel (KDE Plasma 6, Wayland).

Почему dbus-python, а не QtDBus: PySide6 не умеет маршаллить `ai`/`a(ai)`,
а именно такие подписи у setShortcutKeys.

Важно про соединение: раньше здесь был отдельный поток с GLib-циклом и приватный
bus, который закрывался при перерегистрации хоткея. Закрытое соединение оставляло
в общем GLib-контексте свои источники, и следующий проход цикла событий Qt падал
в libdbus (`_dbus_hash_table_lookup_int`, SIGSEGV — снято coredump'ом). Поэтому
соединение живёт весь процесс, GLib-события обрабатывает основной цикл Qt, а смена
комбинации — это повторный `setShortcutKeys`, без пересоздания соединения.
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
                for value in inner:
                    if int(value) > 0:
                        return int(value)
    except (TypeError, ValueError):
        return None
    return None


class GlobalHotkey:
    """Регистрация хоткея в KGlobalAccel. Работает в главном потоке Qt."""

    def __init__(
        self,
        on_activate: Callable[[], None],
        on_release: Callable[[], None] | None = None,
        *,
        component: str = APP_NAME,
        friendly: str = APP_TITLE,
        action: str = "toggle",
        action_text: str = "Диктовка",
    ) -> None:
        self.action_id = ActionId(component, action, friendly, action_text)
        self._on_activate = on_activate
        self._on_release = on_release
        self._bus = None
        self._daemon = None
        self._dbus = None
        self._stopped = True
        self._effective: str | None = None
        self._last_fire = 0.0
        self._lock = threading.Lock()

    # --- публичное API --------------------------------------------------
    @property
    def active(self) -> bool:
        return self._bus is not None and not self._stopped

    @property
    def effective(self) -> str | None:
        return self._effective

    def start(self, sequence: str, *, force: bool = False, timeout: float = 8.0) -> str:
        """Зарегистрировать комбинацию. Повторный вызов меняет её на лету.

        force=False — уважаем значение из kglobalshortcutsrc (пользователь мог
        поменять его в System Settings). force=True — применяем нашу комбинацию
        (кнопка «Сохранить» в настройках).
        """
        del timeout  # вызов синхронный, параметр оставлен для совместимости
        with self._lock:
            self._ensure_bus()
            self._stopped = False
            return self._apply(sequence, force)

    def apply_sequence(self, sequence: str, *, force: bool = True) -> str:
        """Сменить комбинацию, не пересоздавая соединение."""
        return self.start(sequence, force=force)

    def stop(self) -> None:
        """Перестать реагировать на активацию.

        Соединение намеренно не закрывается: его GLib-источники остаются в общем
        контексте, и закрытие уже приводило к падению в libdbus при следующем
        проходе цикла событий Qt.
        """
        self._stopped = True

    # --- внутреннее -----------------------------------------------------
    def _ensure_bus(self) -> None:
        if self._bus is not None:
            return
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop

        # Один раз на процесс: дальше GLib-источники обрабатывает цикл событий Qt.
        DBusGMainLoop(set_as_default=True)
        self._dbus = dbus
        self._bus = dbus.SessionBus(private=True)
        self._daemon = dbus.Interface(self._bus.get_object(SERVICE, OBJECT_PATH), INTERFACE)
        for signal_name in ("globalShortcutPressed", "pressed"):
            self._bus.add_signal_receiver(
                self._on_signal_pressed,
                signal_name=signal_name,
                dbus_interface=COMPONENT_INTERFACE,
                bus_name=SERVICE,
            )
        self._bus.add_signal_receiver(
            self._on_signal_released,
            signal_name="globalShortcutReleased",
            dbus_interface=COMPONENT_INTERFACE,
            bus_name=SERVICE,
        )

    def _apply(self, sequence: str, force: bool) -> str:
        dbus = self._dbus
        key = shortcut_to_int(sequence)
        action_list = dbus.Array(self.action_id.as_list(), signature="s")
        keys = dbus.Array(
            [dbus.Struct([dbus.Array([key], signature="i")], signature="ai")],
            signature="(ai)",
        )
        flags = SET_PRESENT | IS_DEFAULT | (NO_AUTOLOADING if force else 0)
        try:
            self._daemon.doRegister(action_list)
            self._daemon.setShortcutKeys(action_list, keys, dbus.UInt32(flags))
            granted = self._daemon.shortcutKeys(action_list)
        except Exception as exc:  # noqa: BLE001 - шина может ответить чем угодно
            raise HotkeyError(f"Не удалось зарегистрировать хоткей: {exc}") from exc

        effective = _first_key(granted)
        if effective is None:
            raise HotkeyError(
                f"Комбинация {sequence} занята другим приложением — назначьте другую"
            )
        if int(effective) != key:
            log.warning(
                "hotkey: kglobalaccel вернул %s вместо %s",
                int_to_shortcut(effective),
                sequence,
            )
        self._effective = int_to_shortcut(effective)
        log.info("hotkey: зарегистрирован %s", self._effective)
        return self._effective

    def _match(self, args: tuple[object, ...]) -> bool:
        """Отфильтровать сигнал по компоненту и действию."""
        if len(args) >= 2:
            component = args[0] if len(args) > 2 else None
            action = args[1] if len(args) > 2 else args[0]
            if component is not None and str(component) != self.action_id.component:
                return False
            return str(action) == self.action_id.action
        return True

    def _on_signal_pressed(self, *args: object) -> None:
        """Сигналы: globalShortcutPressed(component, action, ts) или pressed(actionId, opts)."""
        if not self._match(args) or self._stopped:
            return
        now = time.monotonic()
        if now - self._last_fire < DEBOUNCE_SECONDS:
            return
        self._last_fire = now
        log.debug("hotkey: активация")
        try:
            self._on_activate()
        except Exception:  # noqa: BLE001 - колбэк не должен ломать шину
            log.exception("hotkey: колбэк активации упал")

    def _on_signal_released(self, *args: object) -> None:
        """globalShortcutReleased(component, action, ts) — для push-to-talk."""
        if not self._match(args) or self._stopped or self._on_release is None:
            return
        self._last_fire = 0.0
        try:
            self._on_release()
        except Exception:  # noqa: BLE001
            log.exception("hotkey: колбэк отпускания упал")
