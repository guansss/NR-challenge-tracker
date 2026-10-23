"""Editable Challenge manager used from the Settings dialog."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QLineEdit, QMessageBox,
    QPushButton, QDateTimeEdit, QSpinBox, QVBoxLayout, QWidget,
)

from .challenges import ChallengeType
from .config import challenges_from_config
from .i18n import localized_name, tr
from .models import ANY_NIGHTFARER, NightlordVariant, Progress, Session


class _ChallengeValidationError(ValueError):
    def __init__(self, translation_key: str) -> None:
        super().__init__(translation_key)
        self.translation_key = translation_key


class ChallengeManagerDialog(QDialog):
    def __init__(
        self, config: dict[str, Any], sessions: tuple[Session, ...],
        nightfarers: list[str], parent: QWidget,
        *, language: str,
    ) -> None:
        super().__init__(parent)
        self.config = deepcopy(config)
        self.sessions, self.nightfarers, self.language = sessions, nightfarers, language
        self._sessions_by_id = {session.id: session for session in sessions}
        self.saved_config: dict[str, Any] | None = None
        self._current_challenge_id: str | None = None
        self.setWindowTitle(tr(language, "challenge.manager_title"))
        self.resize(680, 620)
        self.challenge_list = QListWidget()
        self.challenge_list.currentRowChanged.connect(self._load_selected)
        self.name = QLineEdit()
        self.type = QComboBox()
        self.type.addItem(tr(language, "challenge.type.normal"), ChallengeType.NORMAL.value)
        self.type.addItem(tr(language, "challenge.type.winning_streak"), ChallengeType.WINNING_STREAK.value)
        self.nightfarer = QComboBox()
        self.nightfarer.addItem(
            tr(language, "challenge.any_nightfarer"), ANY_NIGHTFARER
        )
        for value in nightfarers:
            self.nightfarer.addItem(localized_name(language, "nightfarers", value), value)
        self.target = QSpinBox()
        self.target.setRange(0, 1_000_000)
        self.initial_current_streak = QSpinBox()
        self.initial_current_streak.setRange(0, 1_000_000)
        self.initial_best_streak = QSpinBox()
        self.initial_best_streak.setRange(0, 1_000_000)
        self.initial_current_streak.valueChanged.connect(
            self.initial_best_streak.setMinimum
        )
        self.start_time = QDateTimeEdit()
        self.start_time.setCalendarPopup(True)
        self.start_time.setDisplayFormat("yyyy/MM/dd HH:mm:ss")
        self.start_time.setDateTime(QDateTime.fromSecsSinceEpoch(0))
        self.start_time.dateTimeChanged.connect(self._update_exclusion_item_states)
        self.exclusions = QListWidget()
        self.exclusions.setMinimumHeight(220)
        form = QFormLayout()
        form.addRow(tr(language, "challenge.name"), self.name)
        form.addRow(tr(language, "challenge.type_label"), self.type)
        form.addRow(tr(language, "challenge.eligible_nightfarer"), self.nightfarer)
        form.addRow(tr(language, "challenge.target"), self.target)
        form.addRow(
            tr(language, "challenge.initial_current_streak"),
            self.initial_current_streak,
        )
        form.addRow(
            tr(language, "challenge.initial_best_streak"),
            self.initial_best_streak,
        )
        form.addRow(tr(language, "challenge.start_time"), self.start_time)
        form.addRow(QLabel(tr(language, "challenge.exclusions")), self.exclusions)
        add = QPushButton(tr(language, "challenge.add"))
        remove = QPushButton(tr(language, "challenge.delete"))
        add.clicked.connect(self._add)
        remove.clicked.connect(self._delete)
        left = QVBoxLayout()
        left.addWidget(self.challenge_list)
        actions = QHBoxLayout()
        actions.addWidget(add)
        actions.addWidget(remove)
        left.addLayout(actions)
        right = QVBoxLayout()
        right.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            tr(language, "common.save")
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            tr(language, "common.cancel")
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)
        layout = QHBoxLayout(self)
        left_container, right_container = QWidget(), QWidget()
        left_container.setLayout(left)
        right_container.setLayout(right)
        layout.addWidget(left_container, 1)
        layout.addWidget(right_container, 2)
        self.type.currentIndexChanged.connect(self._toggle_streak_fields)
        self._populate()

    def _populate(self, preferred_id: str | None = None) -> None:
        current_id = self._current_challenge_id
        self._store_selected(current_id)
        self.challenge_list.blockSignals(True)
        self.challenge_list.clear()
        for challenge in self.config["challenges"]:
            item = QListWidgetItem(challenge.get("name", ""))
            item.setData(256, challenge.get("id"))
            self.challenge_list.addItem(item)
        active = self.config["active_challenge_id"]
        requested = preferred_id or current_id
        selected_id = requested if requested and self._has_challenge(requested) else active
        index = next((i for i in range(self.challenge_list.count()) if self.challenge_list.item(i).data(256) == selected_id), 0)
        self.challenge_list.setCurrentRow(index)
        self.challenge_list.blockSignals(False)
        self._current_challenge_id = None
        self._load_selected()

    def _selected(self) -> dict[str, Any] | None:
        item = self.challenge_list.currentItem()
        if item is None:
            return None
        return self._challenge_by_id(item.data(256))

    def _challenge_by_id(self, challenge_id: str | None) -> dict[str, Any] | None:
        if challenge_id is None:
            return None
        return next(
            (value for value in self.config["challenges"] if value.get("id") == challenge_id),
            None,
        )

    def _has_challenge(self, challenge_id: str) -> bool:
        return self._challenge_by_id(challenge_id) is not None

    def _store_selected(self, challenge_id: str | None = None) -> None:
        challenge = self._challenge_by_id(
            challenge_id if challenge_id is not None else self._current_challenge_id
        )
        if challenge is None:
            return
        edited_name = self.name.text().strip()
        if edited_name:
            challenge["name"] = edited_name
        challenge["type"] = self.type.currentData()
        challenge["excluded_session_ids"] = [
            self.exclusions.item(index).data(256)
            for index in range(self.exclusions.count())
            if self.exclusions.item(index).checkState() is Qt.CheckState.Checked
        ]
        challenge["start_time"] = (
            datetime.fromtimestamp(
                self.start_time.dateTime().toSecsSinceEpoch(), timezone.utc
            ).isoformat()
        )
        if challenge["type"] == ChallengeType.WINNING_STREAK.value:
            challenge["eligible_nightfarer"] = self.nightfarer.currentData()
            challenge["target"] = self.target.value()
            challenge["initial_current_streak"] = self.initial_current_streak.value()
            challenge["initial_best_streak"] = self.initial_best_streak.value()
        else:
            challenge.pop("eligible_nightfarer", None)
            challenge.pop("target", None)
            challenge.pop("initial_current_streak", None)
            challenge.pop("initial_best_streak", None)

    def _load_selected(self) -> None:
        self._store_selected(self._current_challenge_id)
        challenge = self._selected()
        if challenge is None:
            self._current_challenge_id = None
            return
        self._current_challenge_id = challenge["id"]
        self.name.setText(challenge["name"])
        self.type.setCurrentIndex(self.type.findData(challenge["type"]))
        parsed_challenge = challenges_from_config({"challenges": [challenge]})[0]
        self.start_time.setDateTime(
            QDateTime.fromSecsSinceEpoch(round(parsed_challenge.start_time.timestamp()))
        )
        self.nightfarer.setCurrentIndex(
            self.nightfarer.findData(
                challenge.get("eligible_nightfarer", ANY_NIGHTFARER)
            )
        )
        self.target.setValue(challenge.get("target", 100))
        self.initial_current_streak.setValue(
            challenge.get("initial_current_streak", 0)
        )
        self.initial_best_streak.setMinimum(self.initial_current_streak.value())
        self.initial_best_streak.setValue(challenge.get("initial_best_streak", 0))
        excluded = set(challenge.get("excluded_session_ids", []))
        self.exclusions.clear()
        for session in sorted(self.sessions, key=lambda value: value.started_at, reverse=True):
            item = QListWidgetItem(self._format_session(session))
            item.setData(256, session.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if session.id in excluded else Qt.CheckState.Unchecked
            )
            self.exclusions.addItem(item)
        self._update_exclusion_item_states()
        self._toggle_streak_fields()

    def _update_exclusion_item_states(self) -> None:
        start_time = datetime.fromtimestamp(
            self.start_time.dateTime().toSecsSinceEpoch(), timezone.utc
        )
        for index in range(self.exclusions.count()):
            item = self.exclusions.item(index)
            session = self._sessions_by_id.get(item.data(256))
            if session is None:
                continue
            flags = item.flags()
            if session.started_at < start_time:
                item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled)
            else:
                item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled)

    def _format_session(self, session: Session) -> str:
        nightfarer = (
            localized_name(self.language, "nightfarers", session.nightfarer)
            if session.nightfarer
            else tr(self.language, "common.unknown")
        )
        if session.nightlord_hidden and not session.nightlord_name:
            nightlord = tr(self.language, "session.hidden_nightlord")
        elif session.nightlord_name:
            nightlord = localized_name(
                self.language, "nightlords", session.nightlord_name
            )
            if session.nightlord_variant is NightlordVariant.EVERDARK:
                nightlord = tr(
                    self.language, "variant.everdark_nightlord", nightlord=nightlord
                )
            elif session.nightlord_variant is NightlordVariant.UNKNOWN:
                nightlord = f"{nightlord} (?)"
        else:
            nightlord = tr(self.language, "session.unknown_nightlord")
        outcome = {
            Progress.DAY_1: tr(self.language, "outcome.day_1"),
            Progress.DAY_2: tr(self.language, "outcome.day_2"),
            Progress.DAY_3: tr(self.language, "outcome.day_3"),
            Progress.DAY_3_VICTORY: tr(self.language, "outcome.victory"),
        }.get(session.progress, tr(self.language, "common.unknown"))
        started_at = session.started_at.astimezone().strftime("%Y/%m/%d %H:%M:%S")
        return f"{started_at} {nightfarer} - {nightlord} - {outcome}"

    def _toggle_streak_fields(self) -> None:
        enabled = self.type.currentData() == ChallengeType.WINNING_STREAK.value
        self.nightfarer.setEnabled(enabled)
        self.target.setEnabled(enabled)
        self.initial_current_streak.setEnabled(enabled)
        self.initial_best_streak.setEnabled(enabled)

    def _add(self) -> None:
        self._store_selected(self._current_challenge_id)
        new_challenge = {
            "id": str(uuid4()), "name": tr(self.language, "challenge.new"),
            "type": ChallengeType.NORMAL.value, "excluded_session_ids": [],
            "start_time": (
                datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            ),
        }
        self.config["challenges"].append(new_challenge)
        self._populate(new_challenge["id"])

    def _delete(self) -> None:
        if len(self.config["challenges"]) == 1:
            QMessageBox.warning(self, self.windowTitle(), tr(self.language, "challenge.last_cannot_delete"))
            return
        challenge = self._selected()
        if challenge is None:
            return
        self._store_selected(self._current_challenge_id)
        self.config["challenges"].remove(challenge)
        if self.config["active_challenge_id"] == challenge["id"]:
            self.config["active_challenge_id"] = self.config["challenges"][0]["id"]
        self._current_challenge_id = None
        self._populate(self.config["active_challenge_id"])

    def _save(self) -> None:
        self._store_selected(self._current_challenge_id)
        try:
            challenges = challenges_from_config(self.config)
            if len({challenge.id for challenge in challenges}) != len(challenges):
                raise _ChallengeValidationError("challenge.duplicate_ids")
            if self.config["active_challenge_id"] not in {
                challenge.id for challenge in challenges
            }:
                raise _ChallengeValidationError(
                    "challenge.active_challenge_missing"
                )
        except _ChallengeValidationError as error:
            error_message = tr(self.language, error.translation_key)
        except ValueError as error:
            error_message = tr(
                self.language,
                "common.error_details",
                error=str(error),
            )
        else:
            self.saved_config = self.config
            self.accept()
            return
        QMessageBox.warning(
            self,
            self.windowTitle(),
            tr(self.language, "challenge.save_error", error=error_message),
        )
