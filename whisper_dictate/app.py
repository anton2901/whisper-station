"""Приложение: иконка в трее, HUD, глобальный хоткей и IPC для CLI."""

from __future__ import annotations

import json
import logging
import os
import signal
import time
import sys
import threading

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import APP_NAME, APP_TITLE, __version__, autostart as autostart_mod, icons, ipc, paths, rules
from .config import Config, save
from .controller import RECORDING, STARTING, TRANSCRIBING, Controller
from .hotkey import GlobalHotkey, HotkeyError, kglobalaccel_available
from .hud import Hud
from .inject import stop_ydotoold
from .notify import notify
from .service import ServerManager, health
from .settings_ui import SettingsDialog

log = logging.getLogger(__name__)

STATE_ICONS = {RECORDING: "recording", STARTING: "busy", TRANSCRIBING: "busy"}
STATE_TITLES = {
    "idle": "готов",
    STARTING: "запускаю сервер…",
    RECORDING: "запись",
    TRANSCRIBING: "распознаю…",
}


def wait_for_free_socket(timeout: float = 12.0) -> bool:
    """Дождаться полного выхода прежнего демона.

    Важно для KGlobalAccel: пока живо соединение старого процесса, KWin
    держит компонент «whisper-dictate». Если зарегистрироваться раньше,
    запись исчезнет вместе со старым соединением, и хоткей перестанет
    срабатывать. Мёртвый сокет (после SIGKILL) подчищаем сами.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not ipc.socket_exists():
            return True
        if not ipc.listening():
            paths.ipc_socket().unlink(missing_ok=True)
            return True
        time.sleep(0.2)
    return not ipc.socket_exists()


class WhisperDictate(QObject):
    hotkey_activated = Signal()
    # Обновления из фоновых потоков приходят в главный через эти сигналы.
    server_checked = Signal(object)
    notify_async = Signal(str, str, str)

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.server = ServerManager(cfg)
        self.controller = Controller(cfg, self.server)
        self.hud = Hud()
        self.controller.set_hud(self.hud)
        self._hotkey_text = cfg.hotkey
        self._settings_dialog: SettingsDialog | None = None

        self.hotkey = GlobalHotkey(lambda: self.hotkey_activated.emit())
        self._build_tray()
        self._wire()
        self._start_ipc()
        self._sync_hud_rule()
        self._register_hotkey(force=False)
        QTimer.singleShot(400, self._check_server_async)

    # --- построение UI --------------------------------------------------
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(icons.tray_icon("idle"), self)
        self.menu = QMenu()

        self.status_action = QAction("Сервер: проверяю…", self)
        self.status_action.setEnabled(False)
        self.record_action = QAction(f"Записать ({self._hotkey_text})", self)
        self.server_action = QAction("Запустить сервер", self)
        self.server_action.setVisible(False)
        self.settings_action = QAction("Настройки…", self)
        self.log_action = QAction("Открыть лог", self)
        self.quit_action = QAction("Выход", self)

        self.menu.addAction(self.status_action)
        self.menu.addSeparator()
        self.menu.addAction(self.record_action)
        self.menu.addAction(self.server_action)
        self.menu.addSeparator()
        self.menu.addAction(self.settings_action)
        self.menu.addAction(self.log_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)
        self.tray.setToolTip(f"{APP_TITLE}: {self._hotkey_text}")
        self.tray.show()

    def _wire(self) -> None:
        self.record_action.triggered.connect(self.controller.toggle)
        self.server_action.triggered.connect(self.start_server)
        self.settings_action.triggered.connect(self.open_settings)
        self.log_action.triggered.connect(self.open_log)
        self.quit_action.triggered.connect(self.quit)
        self.tray.activated.connect(self._on_tray_activated)

        self.controller.state_changed.connect(self._on_state_changed)
        self.controller.level_changed.connect(self.hud.set_level)
        self.hud.stop_requested.connect(self.controller.stop)
        self.hud.cancel_requested.connect(self.controller.cancel)
        self.controller.notify_requested.connect(self._notify)
        self.controller.server_status.connect(self._on_server_status)
        self.hotkey_activated.connect(self.controller.toggle)
        self.server_checked.connect(self._on_server_status)
        self.notify_async.connect(self._notify)

    # --- IPC для CLI ----------------------------------------------------
    def _start_ipc(self) -> None:
        self._ipc = QLocalServer(self)
        socket_path = paths.ipc_socket()
        QLocalServer.removeServer(str(socket_path))
        if not self._ipc.listen(str(socket_path)):
            log.warning("ipc: не удалось слушать %s: %s", socket_path, self._ipc.errorString())
        else:
            log.info("ipc: слушаю %s", socket_path)
        self._ipc.newConnection.connect(self._on_new_connection)

    def _on_new_connection(self) -> None:
        while self._ipc.hasPendingConnections():
            connection = self._ipc.nextPendingConnection()
            connection.setParent(self)
            connection.readyRead.connect(lambda conn=connection: self._read_command(conn))
            connection.disconnected.connect(connection.deleteLater)

    def _read_command(self, connection) -> None:
        payload = bytes(connection.readAll()).decode("utf-8", "replace").strip()
        if not payload:
            return
        reply = self.handle_command(payload)
        connection.write((reply + "\n").encode("utf-8"))
        connection.flush()
        connection.disconnectFromServer()

    def handle_command(self, command: str) -> str:
        command = command.strip().lower()
        if command == "toggle":
            self.controller.toggle()
            return "ok"
        if command == "start":
            self.controller.start()
            return "ok"
        if command == "stop":
            self.controller.stop()
            return "ok"
        if command == "cancel":
            self.controller.cancel()
            return "ok"
        if command == "settings":
            QTimer.singleShot(0, self.open_settings)
            return "ok"
        if command == "quit":
            QTimer.singleShot(0, self.quit)
            return "ok"
        if command == "status":
            return json.dumps(self.status())
        return f"error: неизвестная команда {command!r}"

    def status(self) -> dict[str, object]:
        server = health(self.cfg.server_url)
        return {
            "daemon": True,
            "pid": os.getpid(),
            "state": self.controller.state,
            "hotkey": self._hotkey_text,
            "hotkey_active": self.hotkey.active,
            "server": {
                "ok": server.ok,
                "model": server.model,
                "device": server.device,
                "error": server.error,
            },
            "config": str(paths.config_file()),
            "log": str(paths.log_file()),
            "version": __version__,
        }

    # --- хоткей ---------------------------------------------------------
    def _register_hotkey(self, *, force: bool) -> bool:
        if not kglobalaccel_available():
            log.warning("hotkey: org.kde.kglobalaccel недоступен")
            self._notify(
                "Хоткей не зарегистрирован",
                "Нет KGlobalAccel (сессия не KDE?). Назначьте шорткей на команду "
                f"«{APP_NAME} toggle» в настройках системы.",
                "normal",
            )
            self.record_action.setText("Записать")
            return False
        try:
            effective = self.hotkey.start(self.cfg.hotkey, force=force)
        except HotkeyError as exc:
            log.error("hotkey: %s", exc)
            self._notify("Хоткей не зарегистрирован", str(exc), "normal")
            self.record_action.setText("Записать")
            return False
        self._hotkey_text = effective
        self.record_action.setText(
            "Остановить" if self.controller.state == RECORDING else f"Записать ({effective})"
        )
        self.tray.setToolTip(f"{APP_TITLE}: {effective}")
        return True

    # --- позиция HUD ----------------------------------------------------
    def _sync_hud_rule(self) -> None:
        """Закрепить HUD сверху по центру правилом KWin (Wayland иначе нельзя)."""
        if not self.cfg.hud_pin_top:
            rules.remove_rule()
            return
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.geometry()
        x, y = rules.hud_position(area.x(), area.y(), area.width())
        if not rules.ensure_rule(x, y):
            log.info("hud: правило KWin недоступно, позицию выберет композитор")

    # --- обработчики ----------------------------------------------------
    def _on_state_changed(self, state: str) -> None:
        self.tray.setIcon(icons.tray_icon(STATE_ICONS.get(state, "idle")))
        self.tray.setToolTip(f"{APP_TITLE}: {STATE_TITLES.get(state, state)}")
        if state == RECORDING:
            self.record_action.setText("Остановить")
        else:
            self.record_action.setText(
                f"Записать ({self._hotkey_text})" if self._hotkey_text else "Записать"
            )

    def _on_server_status(self, status) -> None:
        if status.ok:
            self.status_action.setText(f"Сервер: {status.device or 'ok'}")
            self.server_action.setVisible(False)
        else:
            self.status_action.setText("Сервер: не запущен")
            self.server_action.setVisible(True)

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.controller.toggle()

    def _notify(self, title: str, body: str, urgency: str) -> None:
        if not notify(title, body, urgency=urgency):
            self.tray.showMessage(title, body, icons.tray_icon("busy"), 5000)

    def _check_server_async(self) -> None:
        def worker() -> None:
            self.server_checked.emit(health(self.cfg.server_url))

        threading.Thread(target=worker, name="whisper-health", daemon=True).start()

    def start_server(self) -> None:
        self.status_action.setText("Сервер: запускаю…")

        def worker() -> None:
            try:
                status = self.server.ensure(timeout=180.0)
            except Exception as exc:  # noqa: BLE001 - показываем пользователю
                self.notify_async.emit("Сервер не запустился", str(exc), "critical")
                self.server_checked.emit(health(self.cfg.server_url))
                return
            self.server_checked.emit(status)

        threading.Thread(target=worker, name="whisper-server", daemon=True).start()

    # --- настройки ------------------------------------------------------
    def open_settings(self) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.raise_()
            return
        dialog = SettingsDialog(self.cfg, self.server)
        self._settings_dialog = dialog
        try:
            if dialog.exec():
                self._apply_settings(dialog.result_config())
        finally:
            self._settings_dialog = None

    def _apply_settings(self, cfg: Config) -> None:
        self.cfg = cfg
        self.controller.cfg = cfg
        save(cfg)
        autostart_mod.apply(cfg.autostart)
        self._sync_hud_rule()
        if not self._register_hotkey(force=True):
            self._notify("Настройки сохранены", "Но хоткей применить не удалось", "normal")
            return
        self._notify("Настройки сохранены", f"Хоткей: {self._hotkey_text}", "low")

    def open_log(self) -> None:
        path = paths.log_file()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # --- выход ----------------------------------------------------------
    def quit(self) -> None:
        log.info("app: выход")
        try:
            self.controller.shutdown()
        except Exception:  # noqa: BLE001 - выходим в любом случае
            log.debug("app: ошибка при shutdown контроллера", exc_info=True)
        try:
            self.hotkey.stop()
            stop_ydotoold()
            self.server.stop_owned()
        except Exception:  # noqa: BLE001
            log.debug("app: ошибка при остановке сервисов", exc_info=True)
        self.hud.finish()
        self.tray.hide()
        try:
            self._ipc.close()
            paths.ipc_socket().unlink(missing_ok=True)
        except OSError:
            pass
        application = QApplication.instance()
        if application is not None:
            application.quit()


def run(cfg: Config, argv: list[str] | None = None) -> int:
    """Точка входа GUI-процесса."""
    paths.ensure_dirs()
    if ipc.status() is not None:
        print(f"{APP_NAME}: уже запущен", file=sys.stderr)
        return 0
    if ipc.socket_exists() and not wait_for_free_socket():
        print(f"{APP_NAME}: уже запущен", file=sys.stderr)
        return 0

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_TITLE)
    app.setDesktopFileName(APP_NAME)
    app.setWindowIcon(icons.app_icon())
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.error("app: системный трей недоступен — приложение не сможет работать")
        print(f"{APP_NAME}: нет системного трея (StatusNotifierItem)", file=sys.stderr)
        return 2

    application = WhisperDictate(cfg)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: application.quit())

    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start(250)

    return app.exec()
