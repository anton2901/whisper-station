"""Окно настроек: всё, что перечислено в ТЗ, в одном диалоге."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QListWidget,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import APP_TITLE, __version__
from . import autostart as autostart_mod
from . import catalog, models, server_env
from .config import (
    AUDIO_BACKENDS,
    HOTKEY_MODES,
    INSERT_MODES,
    LANGUAGES,
    MAX_RECORD_SECONDS,
    MAX_THREADS,
    MAX_WORD_LENGTH,
    MODEL_COMPUTE,
    MODEL_DEVICES,
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
DEVICE_LABELS = {
    "auto": "Авто: CUDA, если есть, иначе CPU",
    "cuda": "CUDA (NVIDIA)",
    "cpu": "CPU (без видеокарты)",
}
COMPUTE_LABELS = {
    "auto": "Авто: float16 на GPU, int8 на CPU",
    "float16": "float16 — быстрее на GPU",
    "int8": "int8 — экономно на CPU",
    "int8_float16": "int8_float16 — смешанный",
    "float32": "float32 — точнее, медленнее",
}


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, server: ServerManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._server = server
        self.setWindowTitle(f"{APP_TITLE} — настройки")
        self.setMinimumWidth(560)
        self.resize(560, self._initial_height())
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
        self._server_command.setPlaceholderText(
            "пусто — встроенный сервер (whisper-station server install)"
        )
        browse = QPushButton("Обзор…", self)
        browse.clicked.connect(self._browse_command)
        command_row = QHBoxLayout()
        command_row.addWidget(self._server_command, 1)
        command_row.addWidget(browse)
        self._server_autostart = QCheckBox("Запускать сервер самому, если он не отвечает", self)
        self._server_autostart.setChecked(cfg.server_autostart)

        self._model = QComboBox(self)
        self._fill_models(cfg.model_name)
        self._model.currentIndexChanged.connect(self._on_model_changed)
        self._model_device = QComboBox(self)
        for value in MODEL_DEVICES:
            self._model_device.addItem(DEVICE_LABELS.get(value, value), value)
        self._model_device.setCurrentIndex(max(0, self._model_device.findData(cfg.model_device)))
        self._model_device.currentIndexChanged.connect(self._on_model_changed)
        self._model_compute = QComboBox(self)
        for value in MODEL_COMPUTE:
            self._model_compute.addItem(COMPUTE_LABELS.get(value, value), value)
        self._model_compute.setCurrentIndex(max(0, self._model_compute.findData(cfg.model_compute)))
        self._model_threads = QSpinBox(self)
        self._model_threads.setRange(0, MAX_THREADS)
        self._model_threads.setSpecialValueText("авто")
        self._model_threads.setSuffix(" потоков")
        self._model_threads.setValue(cfg.model_threads)
        self._model_hint = QLabel("", self)
        self._model_hint.setWordWrap(True)
        download = QPushButton("Скачать модель", self)
        download.clicked.connect(self._download_model)
        model_row = QHBoxLayout()
        model_row.addWidget(self._model, 1)
        model_row.addWidget(download)
        self._on_model_changed()

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

        self._words = QListWidget(self)
        self._words.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._words.setMinimumHeight(86)
        self._words.setToolTip("Термины, которые Whisper путает: исправляются после распознавания")
        for word in cfg.dictionary_words:
            self._words.addItem(word)
        self._word_input = QLineEdit(self)
        self._word_input.setPlaceholderText("Новый термин или имя…")
        self._word_input.setMaxLength(MAX_WORD_LENGTH)
        self._word_input.returnPressed.connect(self._add_word)
        self._threshold = QDoubleSpinBox(self)
        self._threshold.setRange(0.0, 1.0)
        self._threshold.setSingleStep(0.01)
        self._threshold.setDecimals(2)
        self._threshold.setValue(cfg.dictionary_threshold)
        self._threshold.setToolTip(
            "Допустимое расхождение: 0 — только точные совпадения, 0.18 — по умолчанию"
        )
        self._remove_fillers = QCheckBox("Убирать филлеры: «ээ», «ммм», «uh», «hmm»", self)
        self._remove_fillers.setChecked(cfg.remove_fillers)
        self._collapse_stutters = QCheckBox("Схлопывать повторы: «я я я» → «я»", self)
        self._collapse_stutters.setChecked(cfg.collapse_stutters)
        self._trailing_space = QCheckBox("Добавлять пробел в конце вставки", self)
        self._trailing_space.setChecked(cfg.trailing_space)

        self._status = QLabel("", self)
        self._status.setWordWrap(True)
        check = QPushButton("Проверить сервер", self)
        check.clicked.connect(self._check_server)

        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self._hotkey_group())
        content_layout.addWidget(self._model_group(model_row))
        content_layout.addWidget(self._transcribe_group(command_row))
        content_layout.addWidget(self._insert_group())
        content_layout.addWidget(self._dictionary_group())
        content_layout.addWidget(self._audio_group())
        content_layout.addWidget(self._misc_group())
        content_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
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
    def _initial_height(self) -> int:
        """Высота окна с запасом, но не больше экрана: содержимое прокручивается."""
        screen = self.screen()
        if screen is None:
            return 720
        return max(480, min(720, screen.availableGeometry().height() - 80))

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

    def _model_group(self, model_row: QHBoxLayout) -> QGroupBox:
        box = QGroupBox("Модель распознавания", self)
        layout = QVBoxLayout(box)
        layout.addLayout(model_row)
        form = QFormLayout()
        form.addRow("Устройство:", self._model_device)
        form.addRow("Расчёт:", self._model_compute)
        form.addRow("Потоки CPU:", self._model_threads)
        layout.addLayout(form)
        if not server_env.is_installed():
            hint = QLabel(
                "Окружения сервера нет: выполните в терминале "
                "«whisper-station server install», потом скачайте модель.",
                box,
            )
            hint.setWordWrap(True)
            layout.addWidget(hint)
        layout.addWidget(self._model_hint)
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

    def _dictionary_group(self) -> QGroupBox:
        box = QGroupBox("Словарь и текст", self)
        layout = QVBoxLayout(box)
        hint = QLabel(
            "Свои термины и имена — исправляются после распознавания, сервер их не знает.",
            box,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(self._words)
        row = QHBoxLayout()
        add = QPushButton("Добавить", box)
        add.clicked.connect(self._add_word)
        remove = QPushButton("Удалить", box)
        remove.clicked.connect(self._remove_words)
        row.addWidget(self._word_input, 1)
        row.addWidget(add)
        row.addWidget(remove)
        layout.addLayout(row)
        form = QFormLayout()
        form.addRow("Порог нечёткого совпадения:", self._threshold)
        layout.addLayout(form)
        layout.addWidget(self._remove_fillers)
        layout.addWidget(self._collapse_stutters)
        layout.addWidget(self._trailing_space)
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

    def _add_word(self) -> None:
        word = " ".join(self._word_input.text().split())
        if not word:
            return
        self._word_input.clear()
        existing = {
            self._words.item(index).text().casefold() for index in range(self._words.count())
        }
        if word.casefold() in existing:
            return
        self._words.addItem(word)

    def _remove_words(self) -> None:
        for item in self._words.selectedItems():
            self._words.takeItem(self._words.row(item))

    # --- модель ---------------------------------------------------------
    def _fill_models(self, current: str) -> None:
        installed = set(models.installed_names())
        self._model.blockSignals(True)
        self._model.clear()
        for info in catalog.CATALOG:
            state = "скачана" if info.name in installed else "не скачана"
            self._model.addItem(f"{info.name} — {info.size_label}, {state}", info.name)
        if current and catalog.get(current) is None:
            self._model.addItem(f"{current} (своя)", current)
        index = self._model.findData(current)
        self._model.setCurrentIndex(index if index >= 0 else 0)
        self._model.blockSignals(False)

    def _on_model_changed(self) -> None:
        name = str(self._model.currentData() or "")
        info = catalog.get(name)
        installed = models.is_installed(name)
        parts = [f"{name}: {'скачана' if installed else 'не скачана'}"]
        if info is not None:
            parts.append(f"{info.size_label}, {info.note}")
        if not installed and info is not None:
            parts.append(f"скачать — кнопка выше, ~{info.size_label}")
        if str(self._model_device.currentData()) == "cpu" and info is not None and info.size_mb >= 1500:
            parts.append("на CPU такая модель считается медленно — лучше small")
        self._model_hint.setText("; ".join(parts))

    def _download_model(self) -> None:
        name = str(self._model.currentData() or "")
        if not name:
            return
        if not server_env.is_installed():
            QMessageBox.warning(
                self,
                "Модель",
                "Сначала установите окружение сервера: whisper-station server install",
            )
            return
        if models.is_installed(name):
            QMessageBox.information(self, "Модель", f"{name} уже скачана")
            return
        problem = models.check_space(name)
        if problem:
            QMessageBox.warning(self, "Модель", problem)
            return

        cancel = threading.Event()
        dialog = QProgressDialog(f"Скачиваю {name}…", "Отмена", 0, 0, self)
        dialog.setWindowTitle("Модель")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.canceled.connect(cancel.set)
        dialog.show()

        done = threading.Event()
        errors: list[str] = []

        def worker() -> None:
            try:
                models.download(name, cancel=cancel)
            except models.ModelError as exc:
                errors.append(str(exc))
            finally:
                done.set()

        threading.Thread(target=worker, name="whisper-model-download", daemon=True).start()

        timer = QTimer(self)

        def tick() -> None:
            if not done.is_set():
                return
            timer.stop()
            dialog.close()
            if errors:
                QMessageBox.critical(self, "Модель", errors[0])
            else:
                self._fill_models(name)
                self._on_model_changed()

        timer.timeout.connect(tick)
        timer.start(300)

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
            model_name=str(self._model.currentData() or self._cfg.model_name),
            model_device=str(self._model_device.currentData()),
            model_compute=str(self._model_compute.currentData()),
            model_threads=int(self._model_threads.value()),
            insert_mode=str(self._mode.currentData()),
            restore_clipboard=self._restore_clipboard.isChecked(),
            restore_delay_ms=int(self._restore_delay.value()),
            paste_shortcut=str(self._paste_shortcut.currentData()),
            dictionary_words=tuple(
                self._words.item(index).text() for index in range(self._words.count())
            ),
            dictionary_threshold=float(self._threshold.value()),
            remove_fillers=self._remove_fillers.isChecked(),
            collapse_stutters=self._collapse_stutters.isChecked(),
            trailing_space=self._trailing_space.isChecked(),
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
