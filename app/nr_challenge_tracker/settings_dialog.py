"""Validated editor for user-overridable application settings."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import (
    EDITABLE_CONFIG_PATHS,
    save_user_config,
    validate_project_config,
)
from .i18n import localized_name, tr


@dataclass(frozen=True, slots=True)
class _Field:
    path: tuple[str, ...]
    group: str
    kind: Literal["text", "int", "float", "bool", "language", "nightfarer"]
    restart_required: bool = False
    minimum: int | float = 0
    maximum: int | float = 1
    decimals: int = 2


_FIELDS = (
    _Field(("language",), "general", "language", True),
    _Field(("capture", "target_window"), "general", "text"),
    _Field(("streak", "target"), "challenge", "int", False, 1, 1000000),
    _Field(
        ("streak", "eligible_nightfarer"),
        "challenge",
        "nightfarer",
    ),
    _Field(("hud", "opacity"), "appearance", "float", False, 0.1, 1, 2),
    _Field(("hud", "font_size"), "appearance", "int", False, 8, 72),
    _Field(("hud", "recent_sessions"), "appearance", "int", False, 1, 100),
    _Field(("debug", "save_screenshots"), "appearance", "bool"),
    _Field(("bilibili", "title_template"), "bilibili", "text"),
    _Field(
        ("bilibili", "polling_interval_seconds"),
        "bilibili",
        "int",
        False,
        1,
        3600,
    ),
    _Field(("api", "host"), "api", "text", True),
    _Field(("api", "port"), "api", "int", True, 1, 65535),
    _Field(
        ("recognition", "consecutive_confirmations"),
        "recognition",
        "int",
        True,
        1,
        30,
    ),
    _Field(
        ("recognition", "sampling", "idle_ms"),
        "recognition",
        "int",
        True,
        1,
        60000,
    ),
    _Field(
        ("recognition", "sampling", "preparation_ms"),
        "recognition",
        "int",
        True,
        1,
        60000,
    ),
    _Field(
        ("recognition", "sampling", "gameplay_ms"),
        "recognition",
        "int",
        True,
        1,
        60000,
    ),
    _Field(
        ("recognition", "sampling", "result_ms"),
        "recognition",
        "int",
        True,
        1,
        60000,
    ),
    _Field(
        ("recognition", "thresholds", "template_score"),
        "recognition",
        "float",
        False,
        0,
        1,
        4,
    ),
    _Field(
        ("recognition", "thresholds", "result_template_score"),
        "recognition",
        "float",
        False,
        0,
        1,
        4,
    ),
    _Field(
        ("recognition", "thresholds", "identity_margin"),
        "recognition",
        "float",
        False,
        0,
        1,
        4,
    ),
    _Field(
        ("recognition", "thresholds", "variant_score_margin"),
        "recognition",
        "float",
        False,
        0,
        1,
        4,
    ),
    _Field(
        ("recognition", "thresholds", "progress_margin"),
        "recognition",
        "float",
        False,
        0,
        1,
        4,
    ),
    _Field(
        ("recognition", "thresholds", "victory_margin"),
        "recognition",
        "float",
        False,
        0,
        1,
        4,
    ),
)

if {field.path for field in _FIELDS} != set(EDITABLE_CONFIG_PATHS):
    raise RuntimeError("Settings dialog fields do not match editable config fields")


class _IgnoreWheelMixin:
    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class _NoWheelComboBox(_IgnoreWheelMixin, QComboBox):
    pass


class _NoWheelSpinBox(_IgnoreWheelMixin, QSpinBox):
    pass


class _NoWheelDoubleSpinBox(_IgnoreWheelMixin, QDoubleSpinBox):
    pass


class SettingsDialog(QDialog):
    def __init__(
        self,
        root: Path,
        defaults: dict[str, Any],
        config: dict[str, Any],
        nightfarers: list[str],
        parent: QWidget | None = None,
        *,
        language: str,
        assets_root: Path,
    ) -> None:
        super().__init__(parent)
        self.root = root
        self.defaults = deepcopy(defaults)
        self.config = deepcopy(config)
        self.nightfarers = nightfarers
        self.language = language
        self.assets_root = assets_root
        self.editors: dict[str, QWidget] = {}
        self.reset_buttons: dict[str, QPushButton] = {}
        self.saved_config: dict[str, Any] | None = None
        self.setWindowTitle(tr(language, "settings.title"))
        self.resize(580, 680)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        groups: dict[str, QFormLayout] = {}
        for field in _FIELDS:
            form = groups.get(field.group)
            if form is None:
                group_box = QGroupBox(tr(language, f"settings.groups.{field.group}"))
                form = QFormLayout(group_box)
                content_layout.addWidget(group_box)
                groups[field.group] = form
            editor = self._create_editor(field)
            field_key = ".".join(field.path)
            self.editors[field_key] = editor
            reset_button = QPushButton(tr(language, "settings.reset"))
            reset_button.setEnabled(
                self._editor_value(editor) != self._value(self.defaults, field.path)
            )
            reset_button.clicked.connect(
                lambda _checked=False, field=field, editor=editor, button=reset_button: self._reset_field(
                    field, editor, button
                )
            )
            self.reset_buttons[field_key] = reset_button
            self._connect_editor_change(editor, reset_button, field)
            label = QLabel(tr(language, f"settings.fields.{field.path[-1]}"))
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(editor, 1)
            if field.restart_required:
                note = QLabel(tr(language, "settings.restart_required"))
                note.setWordWrap(True)
                note.setStyleSheet("color: #a07020;")
                row_layout.addWidget(note)
            row_layout.addWidget(reset_button)
            form.addRow(label, row)

        content_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            tr(language, "common.save")
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            tr(language, "common.cancel")
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(buttons)

    def _create_editor(self, field: _Field) -> QWidget:
        value = self._value(self.config, field.path)
        if field.kind == "language":
            editor = _NoWheelComboBox()
            for label, code in (
                (tr(self.language, "settings.language.auto"), "auto"),
                (tr(self.language, "settings.language.en"), "en"),
                (tr(self.language, "settings.language.zh"), "zh"),
            ):
                editor.addItem(label, code)
            editor.setCurrentIndex(editor.findData(value))
            return editor
        if field.kind == "nightfarer":
            editor = _NoWheelComboBox()
            for name in self.nightfarers:
                editor.addItem(
                    localized_name(self.language, "nightfarers", name), name
                )
            editor.setCurrentIndex(editor.findData(value))
            return editor
        if field.kind == "bool":
            editor = QCheckBox()
            editor.setChecked(value)
            return editor
        if field.kind == "int":
            editor = _NoWheelSpinBox()
            editor.setRange(int(field.minimum), int(field.maximum))
            editor.setValue(value)
            return editor
        if field.kind == "float":
            editor = _NoWheelDoubleSpinBox()
            editor.setRange(float(field.minimum), float(field.maximum))
            editor.setDecimals(field.decimals)
            editor.setSingleStep(0.01)
            editor.setValue(value)
            return editor
        editor = QLineEdit()
        editor.setText(value)
        return editor

    def _save(self) -> None:
        updated = deepcopy(self.config)
        for field in _FIELDS:
            editor = self.editors[".".join(field.path)]
            self._set_value(updated, field.path, self._editor_value(editor))
        try:
            validated, _settings = validate_project_config(
                updated, assets_root=self.assets_root
            )
            save_user_config(self.root, self.defaults, validated)
        except ValueError as error:
            QMessageBox.warning(
                self,
                tr(self.language, "settings.title"),
                tr(self.language, "settings.invalid", error=str(error)),
            )
            return
        self.saved_config = validated
        self.accept()

    def _reset_field(
        self, field: _Field, editor: QWidget, button: QPushButton
    ) -> None:
        self._set_editor_value(editor, self._value(self.defaults, field.path))
        button.setEnabled(
            self._editor_value(editor) != self._value(self.defaults, field.path)
        )

    def _connect_editor_change(
        self, editor: QWidget, button: QPushButton, field: _Field
    ) -> None:
        refresh = lambda *_args: button.setEnabled(
            self._editor_value(editor) != self._value(self.defaults, field.path)
        )
        if isinstance(editor, QComboBox):
            editor.currentIndexChanged.connect(refresh)
        elif isinstance(editor, QCheckBox):
            editor.toggled.connect(refresh)
        elif isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            editor.valueChanged.connect(refresh)
        elif isinstance(editor, QLineEdit):
            editor.textChanged.connect(refresh)

    @staticmethod
    def _editor_value(editor: QWidget) -> Any:
        if isinstance(editor, QComboBox):
            return editor.currentData()
        if isinstance(editor, QCheckBox):
            return editor.isChecked()
        if isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            return editor.value()
        if isinstance(editor, QLineEdit):
            return editor.text()
        raise TypeError(f"Unsupported settings editor: {type(editor).__name__}")

    @staticmethod
    def _set_editor_value(editor: QWidget, value: Any) -> None:
        if isinstance(editor, QComboBox):
            editor.setCurrentIndex(editor.findData(value))
        elif isinstance(editor, QCheckBox):
            editor.setChecked(value)
        elif isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            editor.setValue(value)
        elif isinstance(editor, QLineEdit):
            editor.setText(value)
        else:
            raise TypeError(f"Unsupported settings editor: {type(editor).__name__}")

    @staticmethod
    def _value(config: dict[str, Any], path: tuple[str, ...]) -> Any:
        value: Any = config
        for part in path:
            value = value[part]
        return value

    @staticmethod
    def _set_value(
        config: dict[str, Any], path: tuple[str, ...], value: Any
    ) -> None:
        section = config
        for part in path[:-1]:
            section = section[part]
        section[path[-1]] = value
