"""Transparent PySide6 HUD and manual session resolution controls."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDateTime, QUrl, Qt, Signal, QTimer
from PySide6.QtGui import QDesktopServices, QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDateTimeEdit,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from .models import NightlordVariant, Progress, Session, SessionStatus
from .monitor import RecognitionMonitor
from .sessions import ACTIVE_STATUSES, SessionService, SessionTransitionError
from .streak import StreakStats
from .title_state import TitleState


class ResolveSessionDialog(QDialog):
    def __init__(self, sessions: list[Session], nightfarers: list[str], parent=None):
        super().__init__(parent)
        self._sessions = sessions
        self.setWindowTitle("Resolve session")
        self.session_picker = QComboBox()
        for session in sessions:
            self.session_picker.addItem(
                f"{session.id[:8]} - {session.nightfarer or 'Unknown'}", session.id
            )
        self.nightfarer = QComboBox()
        self.nightfarer.addItem("Unknown", None)
        for name in nightfarers:
            self.nightfarer.addItem(name, name)
        self.nightlord = QLineEdit()
        self.variant = QComboBox()
        for variant in NightlordVariant:
            self.variant.addItem(variant.value.title(), variant)
        self.progress = QComboBox()
        self.progress.addItem("Select outcome", None)
        for label, progress in (
            ("Day 1", Progress.DAY_1),
            ("Day 2", Progress.DAY_2),
            ("Day 3", Progress.DAY_3),
            ("Victory", Progress.DAY_3_VICTORY),
        ):
            self.progress.addItem(label, progress)
        self.started_at = QDateTimeEdit()
        self.started_at.setDisplayFormat("yyyy/MM/dd HH:mm:ss")
        self.started_at.setCalendarPopup(True)
        self.ended_at = QDateTimeEdit()
        self.ended_at.setDisplayFormat("yyyy/MM/dd HH:mm:ss")
        self.ended_at.setCalendarPopup(True)

        form = QFormLayout()
        form.addRow("Session", self.session_picker)
        form.addRow("Nightfarer", self.nightfarer)
        form.addRow("Nightlord", self.nightlord)
        form.addRow("Variant", self.variant)
        form.addRow("Outcome", self.progress)
        form.addRow("Started", self.started_at)
        form.addRow("Ended", self.ended_at)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
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
        self.nightlord.setText(session.nightlord_name or "")
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


class TrackerWindow(QMainWindow):
    updated = Signal(object, str)

    def __init__(
        self,
        sessions: SessionService,
        monitor: RecognitionMonitor,
        title_state: TitleState,
        nightfarers: list[str],
        settings_path: Path,
        *,
        opacity: float = 0.9,
        font_size: int = 14,
        width: int = 420,
    ) -> None:
        super().__init__()
        self.sessions = sessions
        self.monitor = monitor
        self.title_state = title_state
        self.nightfarers = nightfarers
        self.settings_path = settings_path
        self._drag_offset = None
        self.setWindowTitle("Nightreign Challenge Tracker")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(320)
        self.setMaximumWidth(800)
        self.resize(width, 420)

        panel = QWidget()
        alpha = round(opacity * 255)
        panel.setStyleSheet(
            f"QWidget#panel {{ background: rgba(18, 23, 25, {alpha}); "
            "border: 1px solid rgba(167, 190, 174, 110); border-radius: 6px; }"
            "QLabel { color: #e9eee8; }"
            "QPushButton { color: #e9eee8; background: #34443d; border: 0; "
            "padding: 5px 9px; border-radius: 3px; }"
            "QPushButton:hover { background: #496457; }"
            "QListWidget { color: #e9eee8; background: transparent; border: 0; }"
        )
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self.heading = QLabel("NIGHTREIGN / TRACKER")
        self.heading.setStyleSheet("font-weight: 700; color: #b5d6c1;")
        close_button = QPushButton("×")
        close_button.setFixedWidth(28)
        close_button.clicked.connect(self.close)
        header.addWidget(self.heading)
        header.addStretch(1)
        header.addWidget(close_button)
        layout.addLayout(header)

        self.current_label = QLabel("No active session")
        self.current_label.setWordWrap(True)
        self.current_label.setStyleSheet(f"font-size: {font_size + 2}px; font-weight: 600;")
        self.streak_label = QLabel("0 / 100")
        self.streak_label.setStyleSheet(f"font-size: {font_size + 8}px; color: #9ed7ae;")
        self.monitor_label = QLabel("Starting monitor...")
        self.sync_label = QLabel("Title sync: Pending")
        self.history = QListWidget()
        self.history.setMinimumHeight(150)
        self.history.setMaximumHeight(240)
        layout.addWidget(self.current_label)
        layout.addWidget(self.streak_label)
        layout.addWidget(self.monitor_label)
        layout.addWidget(self.sync_label)
        layout.addWidget(self.history)

        actions = QHBoxLayout()
        self.pause_button = QPushButton("Pause")
        self.skip_button = QPushButton("Skip")
        self.resolve_button = QPushButton("Resolve")
        config_button = QPushButton("Open config")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.skip_button.clicked.connect(self.skip_active)
        self.resolve_button.clicked.connect(self.resolve_session)
        config_button.clicked.connect(self.open_config)
        actions.addWidget(self.pause_button)
        actions.addWidget(self.skip_button)
        actions.addWidget(self.resolve_button)
        actions.addWidget(config_button)
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

    def _refresh_from_signal(self, _payload: object, status: str) -> None:
        self.monitor_label.setText(status)
        self.refresh()

    def refresh(self) -> None:
        snapshot = self.sessions.snapshot
        stats: StreakStats = snapshot.stats
        try:
            title_view = self.title_state.update(stats)
        except ValueError as error:
            title_view = self.title_state.view(stats)
            title_view["sync_status"] = "Title rejected"
            title_view["sync_message"] = str(error)
        self.streak_label.setText(
            f"{stats.current_streak} / {stats.target}  |  Best {stats.best_streak}"
        )
        self.sync_label.setText(
            f"Title sync: {title_view['sync_status']}"
            + (f" · {title_view['sync_message']}" if title_view["sync_message"] else "")
        )
        active = next(
            (session for session in reversed(snapshot.sessions) if session.status in ACTIVE_STATUSES),
            None,
        )
        if active:
            nightlord = (
                "Hidden Nightlord"
                if active.nightlord_hidden and not active.nightlord_name
                else active.nightlord_name or "Unknown Nightlord"
            )
            self.current_label.setText(
                f"Current: {active.nightfarer or 'Unknown'} - {nightlord}"
            )
        else:
            self.current_label.setText("No active session")

        self.history.clear()
        completed = sorted(
            (
                session
                for session in snapshot.sessions
                if session.status is SessionStatus.COMPLETED
            ),
            key=lambda session: session.started_at,
            reverse=True,
        )[:8]
        for session in completed:
            item = QListWidgetItem(_format_session(session, stats))
            item.setData(Qt.ItemDataRole.UserRole, session.id)
            self.history.addItem(item)

    def toggle_pause(self) -> None:
        if not self.monitor._thread or not self.monitor._thread.is_alive():
            self.monitor.start()
            self.pause_button.setText("Pause")
            return
        if self.monitor.is_paused:
            self.monitor.resume()
            self.pause_button.setText("Pause")
            if not self.monitor._thread or not self.monitor._thread.is_alive():
                self.monitor.start()
        else:
            self.monitor.pause()
            self.pause_button.setText("Resume")

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
            QMessageBox.information(self, "Discard session", "Select a session to discard.")
            return
        answer = QMessageBox.question(
            self,
            "Discard session",
            "Exclude this session from streak calculations?",
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
            QMessageBox.information(self, "Resolve session", "There are no sessions to correct.")
            return
        dialog = ResolveSessionDialog(unresolved, self.nightfarers, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        session_id = dialog.session_picker.currentData()
        selected_nightfarer = dialog.nightfarer.currentData()
        session = next(item for item in unresolved if item.id == session_id)
        try:
            selected_progress = dialog.progress.currentData()
            if selected_progress is None:
                raise SessionTransitionError("Select an explicit final outcome")
            self.sessions.resolve_session(
                session_id,
                nightfarer=selected_nightfarer,
                nightlord_name=dialog.nightlord.text().strip() or session.nightlord_name,
                variant=dialog.variant.currentData(),
                progress=selected_progress,
                started_at=dialog.started_at.dateTime().toPython().astimezone(),
                ended_at=dialog.ended_at.dateTime().toPython().astimezone(),
            )
        except (SessionTransitionError, ValueError) as error:
            QMessageBox.warning(self, "Could not resolve session", str(error))
        self.refresh()

    def open_config(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.settings_path)))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        event.accept()

    def closeEvent(self, event) -> None:
        self._refresh_timer.stop()
        self.monitor.stop()
        event.accept()


def _format_session(session: Session, stats: StreakStats) -> str:
    streak_number = stats.streak_numbers.get(session.id)
    number = f"#{streak_number} " if streak_number is not None else ""
    nightlord = session.nightlord_name or "Unknown Nightlord"
    if session.nightlord_variant is NightlordVariant.EVERDARK:
        nightlord = f"Everdark {nightlord}"
    elif session.nightlord_variant is NightlordVariant.UNKNOWN:
        nightlord = f"{nightlord} (?)"
    outcome = {
        Progress.DAY_1: "Day 1",
        Progress.DAY_2: "Day 2",
        Progress.DAY_3: "Day 3",
        Progress.DAY_3_VICTORY: "Victory",
    }.get(session.progress, "Unknown")
    timestamp = session.started_at.astimezone().strftime("%Y/%m/%d %H:%M:%S")
    return f"{number}{session.nightfarer or 'Unknown'} - {nightlord} - {outcome}\n{timestamp}"