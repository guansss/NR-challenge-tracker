"""Transparent PySide6 HUD and manual session resolution controls."""

from __future__ import annotations

import ctypes
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDateTime, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QFont, QFontMetrics, QMouseEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizeGrip,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .i18n import localized_name, tr
from .models import NightlordVariant, Progress, Session, SessionStatus
from .monitor import RecognitionMonitor
from .sessions import ACTIVE_STATUSES, SessionService, SessionTransitionError
from .streak import StreakStats
from .title_state import TitleState

_SCREEN_CUE_FILES = {
    "preparation": "correct.mp3",
    "result": "picked-coin-echo-2.mp3",
}
_SCREEN_CUE_PLAYERS: dict[str, QMediaPlayer] = {}


def _play_screen_cue(screen: str) -> None:
    filename = _SCREEN_CUE_FILES.get(screen)
    if filename is None:
        return
    player = _SCREEN_CUE_PLAYERS.get(screen)
    if player is None:
        player = QMediaPlayer()
        player.setAudioOutput(QAudioOutput(player))
        sound_path = Path(__file__).resolve().parents[2] / "assets" / "sound" / filename
        player.setSource(QUrl.fromLocalFile(str(sound_path)))
        _SCREEN_CUE_PLAYERS[screen] = player
    player.setPosition(0)
    player.play()


class ResolveSessionDialog(QDialog):
    def __init__(
        self,
        sessions: list[Session],
        nightfarers: list[str],
        nightlords: list[str],
        parent=None,
        *,
        language: str = "en",
        selected_session_id: str | None = None,
    ):
        super().__init__(parent)
        self.language = language
        self._sessions = sorted(
            sessions, key=lambda session: session.started_at, reverse=True
        )
        self.setWindowTitle(tr(language, "session.dialog_title"))
        self.session_picker = QComboBox()
        for session in self._sessions:
            nightfarer = (
                localized_name(language, "nightfarers", session.nightfarer)
                if session.nightfarer
                else tr(language, "common.unknown")
            )
            self.session_picker.addItem(
                f"{session.id[:8]} - {nightfarer}",
                session.id,
            )
        if selected_session_id is not None:
            selected_index = self.session_picker.findData(selected_session_id)
            if selected_index >= 0:
                self.session_picker.setCurrentIndex(selected_index)
        self.nightfarer = QComboBox()
        self.nightfarer.addItem(tr(language, "common.unknown"), None)
        for name in nightfarers:
            self.nightfarer.addItem(localized_name(language, "nightfarers", name), name)
        self.nightlord = QComboBox()
        self.nightlord.addItem(tr(language, "session.select_nightlord"), None)
        for name in nightlords:
            self.nightlord.addItem(localized_name(language, "nightlords", name), name)
        self.variant = QComboBox()
        for variant in NightlordVariant:
            self.variant.addItem(tr(language, f"variant.{variant.value}"), variant)
        self.progress = QComboBox()
        self.progress.addItem(tr(language, "outcome.select"), None)
        for label, progress in (
            (tr(language, "outcome.day_1"), Progress.DAY_1),
            (tr(language, "outcome.day_2"), Progress.DAY_2),
            (tr(language, "outcome.day_3"), Progress.DAY_3),
            (tr(language, "outcome.victory"), Progress.DAY_3_VICTORY),
        ):
            self.progress.addItem(label, progress)
        self.started_at = QDateTimeEdit()
        self.started_at.setDisplayFormat("yyyy/MM/dd HH:mm:ss")
        self.started_at.setCalendarPopup(True)
        self.ended_at = QDateTimeEdit()
        self.ended_at.setDisplayFormat("yyyy/MM/dd HH:mm:ss")
        self.ended_at.setCalendarPopup(True)

        form = QFormLayout()
        form.addRow(tr(language, "session.fields.session"), self.session_picker)
        form.addRow(tr(language, "session.fields.nightfarer"), self.nightfarer)
        form.addRow(tr(language, "session.fields.nightlord"), self.nightlord)
        form.addRow(tr(language, "session.fields.variant"), self.variant)
        form.addRow(tr(language, "session.fields.outcome"), self.progress)
        form.addRow(tr(language, "session.fields.started"), self.started_at)
        form.addRow(tr(language, "session.fields.ended"), self.ended_at)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            tr(language, "common.save")
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            tr(language, "common.cancel")
        )
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.session_picker.currentIndexChanged.connect(self._load_session)
        self._load_session()

    def _load_session(self) -> None:
        session_id = self.session_picker.currentData()
        session = next((item for item in self._sessions if item.id == session_id), None)
        if session is None:
            return
        nightfarer_index = self.nightfarer.findData(session.nightfarer)
        self.nightfarer.setCurrentIndex(max(0, nightfarer_index))
        nightlord_index = self.nightlord.findData(session.nightlord_name)
        self.nightlord.setCurrentIndex(max(0, nightlord_index))
        self.variant.setCurrentIndex(self.variant.findData(session.nightlord_variant))
        self.started_at.setDateTime(
            QDateTime.fromSecsSinceEpoch(round(session.started_at.timestamp()))
        )
        self.ended_at.setDateTime(
            QDateTime.fromSecsSinceEpoch(
                round((session.ended_at or datetime.now().astimezone()).timestamp())
            )
        )
        progress_index = self.progress.findData(session.progress)
        self.progress.setCurrentIndex(
            progress_index if session.status is SessionStatus.COMPLETED else 0
        )

    def selected_progress(self) -> Progress | None:
        value = self.progress.currentData()
        return Progress(value) if value is not None else None

    def selected_variant(self) -> NightlordVariant:
        return NightlordVariant(self.variant.currentData())


class ToggleSelectionListWidget(QListWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._selected_item_on_press = False
        self._pressed_item: QListWidgetItem | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        item = self.itemAt(event.position().toPoint())
        self._selected_item_on_press = (
            event.button() == Qt.MouseButton.LeftButton
            and item is not None
            and item.isSelected()
        )
        self._pressed_item = item
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        if (
            self._selected_item_on_press
            and self.itemAt(event.position().toPoint()) is self._pressed_item
        ):
            self.clearSelection()
            self.setCurrentItem(None)
        self._selected_item_on_press = False
        self._pressed_item = None


class TrackerWindow(QMainWindow):
    updated = Signal(object, str)
    geometry_saved = Signal(int, int, int, int)
    _LOCK_HOTKEY_ID = 1

    def __init__(
        self,
        sessions: SessionService,
        monitor: RecognitionMonitor,
        title_state: TitleState,
        nightfarers: list[str],
        nightlords: list[str],
        *,
        opacity: float = 0.9,
        font_size: int = 14,
        width: int = 420,
        recent_sessions: int = 10,
        language: str = "en",
        initial_geometry: tuple[int, int, int, int] | None = None,
    ) -> None:
        super().__init__()
        self.sessions = sessions
        self.monitor = monitor
        self.title_state = title_state
        self.language = language
        self.nightfarers = nightfarers
        self.nightlords = nightlords
        self.recent_sessions = recent_sessions
        self._drag_offset = None
        self._mouse_passthrough = False
        self._hotkey_registered = False
        self._live_result: dict[str, Any] | None = None
        self.setWindowTitle(tr(language, "app.title"))
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(320)
        self.setMaximumWidth(800)
        self.resize(width, 420)
        if initial_geometry is not None:
            self.setGeometry(*initial_geometry)

        panel = QWidget()
        panel_font = panel.font()
        panel_font.setPixelSize(font_size)
        panel.setFont(panel_font)
        alpha = round(opacity * 255)
        panel.setStyleSheet(
            f"QWidget#panel {{ background: rgba(18, 23, 25, {alpha}); "
            "border: 1px solid rgba(167, 190, 174, 110); border-radius: 6px; }"
            "QLabel { color: #e9eee8; }"
            "QPushButton { color: #e9eee8; background: transparent; border: 1px solid transparent; "
            "padding: 5px 9px; border-radius: 3px; }"
            "QPushButton:hover { background: rgba(73, 100, 87, 150); }"
            'QPushButton#lockButton[locked="true"]:hover { background: transparent; }'
            "QListWidget { color: #e9eee8; background: transparent; border: 0; }"
            "QListWidget::item { border: 0; padding-left: 0; }"
            "QListWidget::item:selected { background: rgba(73, 100, 87, 180); }"
        )
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self.heading = QLabel(tr(language, "hud.heading"))
        self.heading.setFont(panel_font)
        self.heading.setStyleSheet("font-weight: 700; color: #b5d6c1;")
        close_button = QPushButton("×")
        close_button.setFont(panel_font)
        close_button.setFixedWidth(28)
        close_button.clicked.connect(self.close)
        header.addWidget(self.heading)
        header.addStretch(1)
        header.addWidget(close_button)
        layout.addLayout(header)

        self.current_label = QLabel(tr(language, "hud.no_active_session"))
        self.current_label.setWordWrap(True)
        current_font = QFont(panel_font)
        current_font.setPixelSize(int(font_size * 1.1))
        current_font.setWeight(QFont.Weight.DemiBold)
        self.current_label.setFont(current_font)
        self.streak_label = QLabel("0 / 100")
        streak_font = QFont(panel_font)
        streak_font.setPixelSize(int(font_size * 1.8))
        self.streak_label.setFont(streak_font)
        self.streak_label.setStyleSheet("color: #9ed7ae;")
        self.monitor_label = QLabel(tr(language, "monitor.starting"))
        self.monitor_label.setFont(panel_font)
        self.sync_label = QLabel(
            tr(language, "hud.title_sync", status=tr(language, "sync.pending"))
        )
        self.sync_label.setFont(panel_font)
        self.history = ToggleSelectionListWidget()
        self.history.setFont(panel_font)
        self.history.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.history.setMinimumHeight(150)
        layout.addWidget(self.streak_label)
        layout.addWidget(self.current_label)
        layout.addWidget(self.history, 1)
        layout.addWidget(self.monitor_label)
        layout.addWidget(self.sync_label)

        actions = QHBoxLayout()
        self.pause_button = QPushButton(tr(language, "actions.pause"))
        self.skip_button = QPushButton(tr(language, "actions.skip"))
        self.resolve_button = QPushButton(tr(language, "actions.resolve"))
        self.lock_button = QPushButton(tr(language, "actions.lock"))
        self.lock_button.setObjectName("lockButton")
        self.lock_button.setProperty("locked", False)
        for button in (
            self.pause_button,
            self.skip_button,
            self.resolve_button,
            self.lock_button,
        ):
            button.setFont(panel_font)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button_size = button.sizeHint()
            if button is self.lock_button:
                locked_text_width = (
                    QFontMetrics(panel_font).horizontalAdvance(
                        tr(language, "actions.locked")
                    )
                    + 20
                )
                button_size.setWidth(max(button_size.width(), locked_text_width))
            button.setFixedSize(button_size)
        self.lock_button.setToolTip(tr(language, "actions.lock_tooltip"))
        self.pause_button.clicked.connect(self.toggle_pause)
        self.skip_button.clicked.connect(self.skip_active)
        self.resolve_button.clicked.connect(self.resolve_session)
        self.lock_button.clicked.connect(self.toggle_mouse_passthrough)
        actions.addWidget(self.pause_button)
        actions.addWidget(self.skip_button)
        actions.addWidget(self.resolve_button)
        actions.addWidget(self.lock_button)
        layout.addLayout(actions)
        resize_row = QHBoxLayout()
        resize_row.addStretch(1)
        resize_row.addWidget(QSizeGrip(panel))
        layout.addLayout(resize_row)
        self.setCentralWidget(panel)

        self.updated.connect(self._refresh_from_signal)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start(1000)
        self.refresh()

    def monitor_update(self, payload: dict[str, Any], status: str) -> None:
        self.updated.emit(payload, status)

    def _refresh_from_signal(self, payload: object, status: str) -> None:
        screen_entry = (
            payload.get("screen_entry") if isinstance(payload, dict) else None
        )
        if screen_entry in {"preparation", "result"}:
            _play_screen_cue(screen_entry)
        recognition = payload.get("recognition") if isinstance(payload, dict) else None
        self._live_result = (
            recognition
            if isinstance(recognition, dict) and recognition.get("screen") == "result"
            else None
        )
        status_values = (
            payload.get("status_values") if isinstance(payload, dict) else None
        )
        if not isinstance(status_values, dict):
            status_values = {}
        self.monitor_label.setText(tr(self.language, status, **status_values))
        self.refresh()

    def refresh(self) -> None:
        snapshot = self.sessions.snapshot
        stats: StreakStats = snapshot.stats
        try:
            title_view = self.title_state.update(stats)
        except ValueError as error:
            title_view = self.title_state.view(stats)
            title_view["sync_status"] = "sync.title_rejected"
            title_view["sync_message"] = str(error)
        self.streak_label.setText(
            tr(
                self.language,
                "hud.streak",
                current=stats.current_streak,
                target=stats.target,
                best=stats.best_streak,
            )
        )
        self.sync_label.setText(
            tr(
                self.language,
                "hud.title_sync",
                status=tr(self.language, title_view["sync_status"]),
            )
            + (f" · {title_view['sync_message']}" if title_view["sync_message"] else "")
        )
        active = next(
            (
                session
                for session in reversed(snapshot.sessions)
                if session.status in ACTIVE_STATUSES
            ),
            None,
        )
        if active:
            if active.nightlord_hidden and not active.nightlord_name:
                nightlord = tr(self.language, "session.hidden_nightlord")
            elif active.nightlord_name:
                nightlord = localized_name(
                    self.language, "nightlords", active.nightlord_name
                )
            else:
                nightlord = tr(self.language, "session.unknown_nightlord")
            current_text = tr(
                self.language,
                "hud.current",
                nightfarer=(
                    localized_name(self.language, "nightfarers", active.nightfarer)
                    if active.nightfarer
                    else tr(self.language, "common.unknown")
                ),
                nightlord=nightlord,
            )
        else:
            current_text = tr(self.language, "hud.no_active_session")
        if self._live_result is not None:
            current_text += "\n" + self._format_live_result(self._live_result)
        self.current_label.setText(current_text)

        selected_item = self.history.currentItem()
        selected_id = (
            selected_item.data(Qt.ItemDataRole.UserRole) if selected_item else None
        )
        self.history.clear()
        recent_sessions = sorted(
            (
                session
                for session in snapshot.sessions
                if session.status is not SessionStatus.DISCARDED
                and (active is None or session.id != active.id)
            ),
            key=lambda session: session.started_at,
            reverse=True,
        )[: self.recent_sessions]
        for session in recent_sessions:
            item = QListWidgetItem(_format_session(session, stats, self.language))
            item.setData(Qt.ItemDataRole.UserRole, session.id)
            self.history.addItem(item)
            if session.id == selected_id:
                self.history.setCurrentItem(item)

    def _format_live_result(self, recognition: dict[str, Any]) -> str:
        nightlord_id = recognition.get("nightlord")
        nightlord = (
            localized_name(self.language, "nightlords", str(nightlord_id))
            if nightlord_id not in (None, "unknown")
            else tr(self.language, "hud.unknown_nightlord")
        )
        variant = recognition.get("variant")
        variant_label = (
            tr(self.language, f"variant.{variant}")
            if variant in {"normal", "everdark"}
            else tr(self.language, "variant.unknown")
        )
        outcome = recognition.get("outcome")
        outcome_keys = {
            "day_1": "outcome.day_1",
            "day_2": "outcome.day_2",
            "day_3": "outcome.day_3",
            "day_3_victory": "outcome.day_3_victory",
            "victory": "outcome.victory",
        }
        outcome_key = outcome_keys.get(outcome)
        outcome_label = (
            tr(self.language, outcome_key)
            if outcome_key is not None
            else tr(self.language, "hud.unknown_outcome")
        )
        return tr(
            self.language,
            "hud.result",
            nightlord=nightlord,
            variant=variant_label,
            outcome=outcome_label,
        )

    def toggle_mouse_passthrough(self) -> None:
        if self._mouse_passthrough:
            self._disable_mouse_passthrough()
            return

        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
        self.show()
        if os.name == "nt":
            register_hotkey = ctypes.windll.user32.RegisterHotKey
            register_hotkey.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.c_uint,
            ]
            register_hotkey.restype = ctypes.c_int
            registered = register_hotkey(
                int(self.winId()), self._LOCK_HOTKEY_ID, 0x0002 | 0x0004 | 0x4000, 0x4C
            )
            if not registered:
                self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, False)
                self.show()
                QMessageBox.warning(
                    self,
                    tr(self.language, "errors.could_not_lock"),
                    tr(self.language, "errors.hotkey_in_use"),
                )
                return
            self._hotkey_registered = True
        self._mouse_passthrough = True
        self.lock_button.setText(tr(self.language, "actions.locked"))
        self._set_lock_button_locked(True)

    def _set_lock_button_locked(self, locked: bool) -> None:
        self.lock_button.setProperty("locked", locked)
        style = self.lock_button.style()
        style.unpolish(self.lock_button)
        style.polish(self.lock_button)
        self.lock_button.update()

    def _disable_mouse_passthrough(self) -> None:
        if self._hotkey_registered and os.name == "nt":
            self._unregister_lock_hotkey()
            self._hotkey_registered = False
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, False)
        self._mouse_passthrough = False
        self.lock_button.setText(tr(self.language, "actions.lock"))
        self._set_lock_button_locked(False)
        self.show()

    def nativeEvent(self, event_type, message):
        if os.name == "nt" and event_type == b"windows_generic_MSG":
            from ctypes.wintypes import MSG

            native_message = ctypes.cast(
                ctypes.c_void_p(int(message)), ctypes.POINTER(MSG)
            ).contents
            if (
                native_message.message == 0x0312
                and native_message.wParam == self._LOCK_HOTKEY_ID
            ):
                self._disable_mouse_passthrough()
                return True, 0
        return super().nativeEvent(event_type, message)

    def _unregister_lock_hotkey(self) -> None:
        unregister_hotkey = ctypes.windll.user32.UnregisterHotKey
        unregister_hotkey.argtypes = [ctypes.c_void_p, ctypes.c_int]
        unregister_hotkey.restype = ctypes.c_int
        unregister_hotkey(int(self.winId()), self._LOCK_HOTKEY_ID)

    def toggle_pause(self) -> None:
        if not self.monitor._thread or not self.monitor._thread.is_alive():
            self.monitor.start()
            self.pause_button.setText(tr(self.language, "actions.pause"))
            return
        if self.monitor.is_paused:
            self.monitor.resume()
            self.pause_button.setText(tr(self.language, "actions.pause"))
            if not self.monitor._thread or not self.monitor._thread.is_alive():
                self.monitor.start()
        else:
            self.monitor.pause()
            self.pause_button.setText(tr(self.language, "actions.resume"))

    def skip_active(self) -> None:
        selected_item = self.history.currentItem()
        selected_id = (
            selected_item.data(Qt.ItemDataRole.UserRole) if selected_item else None
        )
        target = next(
            (
                session
                for session in reversed(self.sessions.snapshot.sessions)
                if session.id == selected_id
            ),
            None,
        )
        if target is None:
            target = next(
                (
                    session
                    for session in reversed(self.sessions.snapshot.sessions)
                    if session.status in ACTIVE_STATUSES
                ),
                None,
            )
        if target is None:
            QMessageBox.information(
                self,
                tr(self.language, "dialogs.discard.title"),
                tr(self.language, "dialogs.discard.select_session"),
            )
            return
        answer = QMessageBox.question(
            self,
            tr(self.language, "dialogs.discard.title"),
            tr(self.language, "dialogs.discard.confirm"),
        )
        if answer is QMessageBox.StandardButton.Yes:
            self.sessions.discard_session(target.id)
            self.refresh()

    def resolve_session(self) -> None:
        unresolved = [
            session
            for session in self.sessions.snapshot.sessions
            if session.status is not SessionStatus.DISCARDED
        ]
        if not unresolved:
            QMessageBox.information(
                self,
                tr(self.language, "session.dialog_title"),
                tr(self.language, "dialogs.resolve.no_sessions"),
            )
            return
        selected_item = self.history.currentItem()
        selected_session_id = (
            selected_item.data(Qt.ItemDataRole.UserRole) if selected_item else None
        )
        dialog = ResolveSessionDialog(
            unresolved,
            self.nightfarers,
            self.nightlords,
            self,
            language=self.language,
            selected_session_id=selected_session_id,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        session_id = dialog.session_picker.currentData()
        selected_nightfarer = dialog.nightfarer.currentData()
        session = next(item for item in unresolved if item.id == session_id)
        try:
            selected_progress = dialog.selected_progress()
            if selected_progress is None:
                raise SessionTransitionError(
                    tr(self.language, "dialogs.resolve.explicit_outcome_required")
                )
            self.sessions.resolve_session(
                session_id,
                nightfarer=selected_nightfarer,
                nightlord_name=dialog.nightlord.currentData(),
                variant=dialog.selected_variant(),
                progress=selected_progress,
                started_at=dialog.started_at.dateTime().toPython().astimezone(),
                ended_at=dialog.ended_at.dateTime().toPython().astimezone(),
            )
        except (SessionTransitionError, ValueError) as error:
            QMessageBox.warning(
                self,
                tr(self.language, "errors.could_not_resolve"),
                str(error),
            )
        self.refresh()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        event.accept()

    def closeEvent(self, event) -> None:
        self._refresh_timer.stop()
        self.geometry_saved.emit(self.x(), self.y(), self.width(), self.height())
        if self._hotkey_registered and os.name == "nt":
            self._unregister_lock_hotkey()
            self._hotkey_registered = False
        self.monitor.stop()
        event.accept()
        application = QApplication.instance()
        if application is not None:
            application.quit()


def _format_session(session: Session, stats: StreakStats, language: str = "en") -> str:
    streak_number = stats.streak_numbers.get(session.id)
    number = f"#{streak_number} " if streak_number is not None else ""
    nightlord = (
        localized_name(language, "nightlords", session.nightlord_name)
        if session.nightlord_name
        else tr(language, "session.unknown_nightlord")
    )
    if session.nightlord_variant is NightlordVariant.EVERDARK:
        nightlord = tr(language, "variant.everdark_nightlord", nightlord=nightlord)
    elif session.nightlord_variant is NightlordVariant.UNKNOWN:
        nightlord = f"{nightlord} (?)"
    outcome = {
        Progress.DAY_1: tr(language, "outcome.day_1"),
        Progress.DAY_2: tr(language, "outcome.day_2"),
        Progress.DAY_3: tr(language, "outcome.day_3"),
        Progress.DAY_3_VICTORY: tr(language, "outcome.victory"),
    }.get(session.progress, tr(language, "common.unknown"))
    timestamp_source = session.ended_at or session.started_at
    timestamp = timestamp_source.astimezone().strftime("%Y/%m/%d %H:%M:%S")
    nightfarer = (
        localized_name(language, "nightfarers", session.nightfarer)
        if session.nightfarer
        else tr(language, "common.unknown")
    )
    return f"{number}{nightfarer} - {nightlord} - {outcome}\n{timestamp}"
