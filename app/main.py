"""Start the Nightreign Challenge Tracker desktop HUD."""

from __future__ import annotations

import os
import signal
import sys

existing_logging_rules = os.environ.get("QT_LOGGING_RULES", "").strip()
os.environ["QT_LOGGING_RULES"] = ";".join(
    rule
    for rule in (
        existing_logging_rules,
        "qt.multimedia.ffmpeg*.debug=false",
        "qt.multimedia.ffmpeg*.info=false",
        "qt.multimedia.ffmpeg*.warning=false",
    )
    if rule
)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from app.nr_challenge_tracker.api import StreakApiServer
from app.nr_challenge_tracker.config import load_project_settings
from app.nr_challenge_tracker.history import HistoryRepository, default_history_path
from app.nr_challenge_tracker.i18n import resolve_language, tr
from app.nr_challenge_tracker.monitor import RecognitionMonitor
from app.nr_challenge_tracker.recognition import RecognitionEngine
from app.nr_challenge_tracker.runtime_paths import application_root, resource_root
from app.nr_challenge_tracker.sessions import SessionService
from app.nr_challenge_tracker.state import StateRepository
from app.nr_challenge_tracker.title_state import TitleState
from app.nr_challenge_tracker.ui import TrackerWindow

ROOT = application_root()
RESOURCES = resource_root()


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("Nightreign Challenge Tracker")
    language = resolve_language("auto")
    signal.signal(signal.SIGINT, lambda *_: application.quit())
    interrupt_timer = QTimer(application)
    interrupt_timer.timeout.connect(lambda: None)
    interrupt_timer.start(250)
    try:
        project_config, settings = load_project_settings(ROOT, assets_root=RESOURCES)
        language = resolve_language(settings.language)
        engine = RecognitionEngine(RESOURCES, project_config)
        history_path = default_history_path(ROOT)
        sessions = SessionService(
            HistoryRepository(
                history_path,
                default_target=settings.target,
                eligible_nightfarer=settings.eligible_nightfarer,
            ),
            everdark_nightlords={
                entry["id"]
                for entry in engine.manifest["nightlords"]
                if entry.get("everdark_available_in_dataset")
            },
        )
        state_repository = StateRepository(ROOT / "state.json")
        title_state = TitleState(
            state_repository,
            settings.title_template,
            settings.title_max_characters,
            settings.room_id if settings.bilibili_enabled else None,
            settings.polling_interval_seconds,
        )
        api = StreakApiServer(
            settings.api_host,
            settings.api_port,
            lambda: _api_view(sessions, title_state),
            title_state.report_sync,
        )
        monitor = RecognitionMonitor(
            engine,
            sessions,
            settings.target_window,
            lambda payload, status: window.monitor_update(payload, status),
            idle_interval_ms=settings.idle_interval_ms,
            preparation_interval_ms=settings.preparation_interval_ms,
            gameplay_interval_ms=settings.gameplay_interval_ms,
            result_interval_ms=settings.result_interval_ms,
            confirmations=settings.consecutive_confirmations,
        )
        window = TrackerWindow(
            sessions,
            monitor,
            title_state,
            [entry["id"] for entry in engine.manifest["nightfarers"]],
            [entry["id"] for entry in engine.manifest["nightlords"]],
            opacity=settings.hud_opacity,
            font_size=settings.hud_font_size,
            width=settings.hud_width,
            recent_sessions=settings.hud_recent_sessions,
            language=language,
            eligible_nightfarer=settings.eligible_nightfarer,
            initial_geometry=state_repository.load_hud_geometry(),
        )
        window.geometry_saved.connect(state_repository.save_hud_geometry)
        api.start()
        window.show()
        monitor.start()
        try:
            return application.exec()
        finally:
            api.close()
    except Exception as error:
        QMessageBox.critical(None, tr(language, "app.title"), str(error))
        return 1


def _api_view(sessions: SessionService, title_state: TitleState) -> dict:
    snapshot = sessions.snapshot
    title = title_state.update(snapshot.stats)
    return {
        **title,
        "current_streak": snapshot.stats.current_streak,
        "target": snapshot.stats.target,
    }


if __name__ == "__main__":
    raise SystemExit(main())
