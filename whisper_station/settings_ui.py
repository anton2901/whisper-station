"""Окно настроек: всё, что перечислено в ТЗ, в одном диалоге."""

from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import APP_TITLE, __version__
from . import autostart as autostart_mod
from .config import (
    AUDIO_BACKENDS,
    HOTKEY_MODES,
    INSERT_MODES,
    LANGUAGES,
    MAX_RECORD_SECONDS,
    PASTE_SHORTCUTS,
    Config,
)
from .service import ServerManager, health

HOTKEY_MODE_LABELS = {
    "toggle": "Переключение: нажал — говоришь, нажал — стоп",
    "press": "Удержание: держишь — пишет, отпустил — вставляет",
}
PASTE_LABELS = {
    "ctrl+v": "Ctrl+V — обычные окна",
    "ctrl+shift+v": "Ctrl+Shift+V — терминалы",
}
MODE_LABELS = {
    "paste": "Буфер + Ctrl+V (рекомендуется)",
    "type": "Посимвольный ввод (ydotool type)",
    "clipboard": "Только буфер обмена",
}
LANGUAGE_LABELS = {"ru": "Русский", "en": "English", "auto": "Определять автоматически"}


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, server: ServerManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._server = server
        self.setWindowTitle(f"{APP_TITLE} — настройки")
        self.setMinimumWidth(520)
        self.setModal(True)

        self._hotkey = QKeySequenceEdit(QKeySequence(cfg.hotkey), self)
        self._hotkey_mode = QComboBox(self)
        for value in HOTKEY_MODES:
            self._hotkey_mode.addItem(HOTKEY_MODE_LABELS.get(value, value), value)
        self._hotkey_mode.setCurrentIndex(max(0, self._hotkey_mode.findData(cfg.hotkey_mode)))
        self._language = QComboBox(self)
        for value in LANGUAGES:
            self._language.addItem(LANGUAGE_LABELS.get(value, value), value)
        self._language.setCurrentIndex(max(0, self._language.findData(cfg.language)))

        self._server_url = QLineEdit(cfg.server_url, self)
        self._server_command = QLineEdit(cfg.server_command, self)
        self._server_command.setPlaceholderText("пусто — найти run.sh автоматически")
        browse = QPushButton("Обзор…", self)
        browse.clicked.connect(self._browse_command)
        command_row = QHBoxLayout()
        command_row.addWidget(self._server_command, 1)
        command_row.addWidget(browse)
        self._server_autostart = QCheckBox("Запускать сервер самому, если он не отвечает", self)
        self._server_autostart.setChecked(cfg.server_autostart)

        self._paste_shortcut = QComboBox(self)
        for value in PASTE_SHORTCUTS:
            self._paste_shortcut.addItem(PASTE_LABELS.get(value, value), value)
        self._paste_shortcut.setCurrentIndex(max(0, self._paste_shortcut.findData(cfg.paste_shortcut)))
        self._mode = QComboBox(self)
        for value in INSERT_MODES:
            self._mode.addItem(MODE_LABELS.get(value, value), value)
        self._mode.setCurrentIndex(max(0, self._mode.findData(cfg.insert_mode)))
        self._restore_clipboard = QCheckBox("Возвращать прежнее содержимое буфера после вставки", self)
        self._restore_clipboard.setChecked(cfg.restore_clipboard)
        self._restore_delay = QSpinBox(self)
        self._restore_delay.setRange(0, 5000)
        self._restore_delay.setSingleStep(50)
        self._restore_delay.setSuffix(" мс")
        self._restore_delay.setValue(cfg.restore_delay_ms)

        self._backend = QComboBox(self)
        for value in AUDIO_BACKENDS:
            self._backend.addItem(value, value)
        self._backend.setCurrentIndex(max(0, self._backend.findData(cfg.audio_backend)))
        self._device = QLineEdit(cfg.audio_device, self)
        self._min_seconds = QDoubleSpinBox(self)
        self._min_seconds.setRange(0.1, 5.0)
        self._min_seconds.setSingleStep(0.05)
        self._min_seconds.setDecimals(2)
        self._min_seconds.setSuffix(" с")
        self._min_seconds.setValue(cfg.min_seconds)
        self._max_seconds = QSpinBox(self)
        self._max_seconds.setRange(5, int(MAX_RECORD_SECONDS))
        self._max_seconds.setSuffix(" с")
        self._max_seconds.setValue(int(cfg.max_seconds))

        self._beep = QCheckBox("Звуковой сигнал старта и остановки", self)
        self._preview_live = QCheckBox("Живой предпросмотр распознавания в HUD", self)
        self._preview_live.setChecked(cfg.preview_live)
        self._beep.setChecked(cfg.beep)
        self._show_hud = QCheckBox("Показывать HUD во время записи", self)
        self._show_hud.setChecked(cfg.show_hud)
        self._hud_pin_top = QCheckBox("Держать HUD сверху по центру (правило KWin)", self)
        self._hud_pin_top.setChecked(cfg.hud_pin_top)
        self._autostart = QCheckBox("Запускать при входе в сессию", self)
        # Состояние берём из файла автозапуска, а не из config.toml: его можно
        # включить командой `whisper-station autostart on`, и тогда сохранение
        # настроек не должно молча выключать автозапуск.
        self._autostart.setChecked(autostart_mod.is_enabled())

        self._status = QLabel("", self)
        self._status.setWordWrap(True)
        check = QPushButton("Проверить сервер", self)
        check.clicked.connect(self._check_server)

        layout = QVBoxLayout(self)
        layout.addWidget(self._hotkey_group())
        layout.addWidget(self._transcribe_group(command_row))
        layout.addWidget(self._insert_group())
        layout.addWidget(self._audio_group())
        layout.addWidget(self._misc_group())
        layout.addLayout(self._status_row(check))
        layout.addWidget(QLabel(f"Версия {__version__}", self))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # --- группы ---------------------------------------------------------
    def _hotkey_group(self) -> QGroupBox:
        box = QGroupBox("Хоткей", self)
        form = QFormLayout(box)
        form.addRow("Глобальная комбинация:", self._hotkey)
        form.addRow("Режим:", self._hotkey_mode)
        hint = QLabel(
            "Комбинацию можно поменять и в System Settings → Shortcuts → Whisper Station.",
            box,
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        return box

    def _transcribe_group(self, command_row: QHBoxLayout) -> QGroupBox:
        box = QGroupBox("Распознавание", self)
        form = QFormLayout(box)
        form.addRow("Язык:", self._language)
        form.addRow("Адрес сервера:", self._server_url)
        form.addRow("Команда запуска:", command_row)
        form.addRow(self._server_autostart)
        return box

    def _insert_group(self) -> QGroupBox:
        box = QGroupBox("Вставка текста", self)
        form = QFormLayout(box)
        form.addRow("Способ:", self._mode)
        form.addRow("Сочетание вставки:", self._paste_shortcut)
        form.addRow(self._restore_clipboard)
        form.addRow("Задержка восстановления буфера:", self._restore_delay)
        hint = QLabel(
            "Ctrl+V эмулируется через ydotool (uinput). Права не меняются: "
            "ydotoold запускается от вашего пользователя.",
            box,
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        return box

    def _audio_group(self) -> QGroupBox:
        box = QGroupBox("Запись", self)
        form = QFormLayout(box)
        form.addRow("Бэкенд:", self._backend)
        form.addRow("Источник:", self._device)
        form.addRow("Минимальная длительность:", self._min_seconds)
        form.addRow("Максимальная длительность:", self._max_seconds)
        return box

    def _misc_group(self) -> QGroupBox:
        box = QGroupBox("Прочее", self)
        layout = QVBoxLayout(box)
        for widget in (
            self._beep,
            self._show_hud,
            self._hud_pin_top,
            self._autostart,
            self._preview_live,
        ):
            layout.addWidget(widget)
        return box

    def _status_row(self, check: QPushButton) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(check)
        row.addWidget(self._status, 1)
        return row

    # --- действия -------------------------------------------------------
    def _browse_command(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Команда запуска сервера", str(self._cfg.server_command))
        if path:
            self._server_command.setText(path)

    def _check_server(self) -> None:
        status = health(self._server_url.text().strip())
        if status.ok:
            self._status.setStyleSheet("color: #2e7d32;")
            self._status.setText(f"Сервер отвечает: {status.describe()}")
        else:
            self._status.setStyleSheet("color: #b3261e;")
            self._status.setText(f"Сервер не отвечает: {status.error or 'нет ответа'}")

    def result_config(self) -> Config:
        sequence = self._hotkey.keySequence().toString()
        return self._cfg.with_changes(
            hotkey=sequence or self._cfg.hotkey,
            hotkey_mode=str(self._hotkey_mode.currentData()),
            language=str(self._language.currentData()),
            server_url=self._server_url.text().strip() or self._cfg.server_url,
            server_command=self._server_command.text().strip(),
            server_autostart=self._server_autostart.isChecked(),
            insert_mode=str(self._mode.currentData()),
            restore_clipboard=self._restore_clipboard.isChecked(),
            restore_delay_ms=int(self._restore_delay.value()),
            paste_shortcut=str(self._paste_shortcut.currentData()),
            audio_backend=str(self._backend.currentData()),
            audio_device=self._device.text().strip() or "@DEFAULT_SOURCE@",
            min_seconds=float(self._min_seconds.value()),
            max_seconds=float(self._max_seconds.value()),
            beep=self._beep.isChecked(),
            preview_live=self._preview_live.isChecked(),
            show_hud=self._show_hud.isChecked(),
            hud_pin_top=self._hud_pin_top.isChecked(),
            autostart=self._autostart.isChecked(),
        )
