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

from app.nr_challenge_tracker.api import TrackerApiServer
from app.nr_challenge_tracker.challenges import analyze_challenge
from app.nr_challenge_tracker.config import load_default_config, load_project_settings
from app.nr_challenge_tracker.history import (
    HistoryRepository,
    default_history_path,
)
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
        defaults_config = load_default_config(RESOURCES)
        language = resolve_language(settings.language)
        engine = RecognitionEngine(RESOURCES, project_config)
        history_path = default_history_path(ROOT)
        sessions = SessionService(
            HistoryRepository(
                history_path,
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
            settings.polling_interval_seconds,
        )
        api = TrackerApiServer(
            settings.api_host,
            settings.api_port,
            lambda: _api_view(sessions, title_state, window),
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
            debug_dir=ROOT / "debug" / "screenshots",
            debug_screenshots_enabled=settings.debug_save_screenshots,
        )
        window = TrackerWindow(
            sessions,
            monitor,
            title_state,
            [entry["id"] for entry in engine.manifest["nightfarers"]],
            [entry["id"] for entry in engine.manifest["nightlords"]],
            opacity=settings.hud_opacity,
            font_size=settings.hud_font_size,
            recent_sessions=settings.hud_recent_sessions,
            always_on_top=settings.hud_always_on_top,
            language=language,
            initial_geometry=state_repository.load_hud_geometry(),
            defaults_config=defaults_config,
            config=project_config,
            config_root=ROOT,
            assets_root=RESOURCES,
        )
        window.settings_saved.connect(
            lambda config: _apply_live_settings(
                config, engine, monitor, title_state, window
            )
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


def _api_view(sessions: SessionService, title_state: TitleState, window: TrackerWindow) -> dict:
    snapshot = sessions.snapshot
    analysis = analyze_challenge(snapshot.sessions, window._active_challenge())
    title = title_state.update(analysis)
    return {
        **title,
    }


def _apply_live_settings(
    config: dict,
    engine: RecognitionEngine,
    monitor: RecognitionMonitor,
    title_state: TitleState,
    window: TrackerWindow,
) -> None:
    monitor.set_target_window(config["capture"]["target_window"])
    engine.update_thresholds(config["recognition"]["thresholds"])
    monitor.debug_screenshots_enabled = config["debug"]["save_screenshots"]
    title_state.title_template = config["bilibili"]["title_template"]
    title_state.polling_interval_seconds = config["bilibili"][
        "polling_interval_seconds"
    ]
    title_state.update(analyze_challenge(window.sessions.snapshot.sessions, window._active_challenge()))
    window.refresh()


if __name__ == "__main__":
    raise SystemExit(main())
