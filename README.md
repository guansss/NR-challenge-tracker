# Nightreign Challenge Tracker

Windows desktop HUD and local session tracker for the Executor 100-victory challenge.

## Run

From the repository root, install dependencies into the project virtual environment and launch the app:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.main
```

The application captures only a visible window whose title contains `capture.target_window` from `config.yaml`. Keep Nightreign in a supported window-capture mode. If capture is unavailable, the app preserves any attempt as interrupted rather than recording a loss.

Session history is stored in `history.yaml` at the project root. Desired-title revision and sync status are stored in the adjacent `title-state.json`. Both generated runtime data files are ignored by Git.

Accepted preparation and result screens are also saved as annotated PNGs under `debug/screenshots/`. Filenames include the 1-based attempt number and recognized identity; an existing file for the same identity is left unchanged.

## Configuration

Set `language` in `config.yaml` to `auto`, `en`, or `zh`. With `auto`, the app checks the system's preferred UI languages in order and uses the first supported language; if neither English nor Chinese is listed, it falls back to English. UI translations are grouped by feature in `assets/translations.yaml`.

Recognition ROIs, confidence thresholds, and sampling intervals are configured separately in `config.yaml`; the supplied values are starting points calibrated against the included 2560x1440 screenshot set. The app validates runtime settings and binds the local API only to a loopback address.

For Bilibili title updates, set `bilibili.room_id` to the target live-room ID and install `app/integrations/bilibili.user.js` in Tampermonkey. Sign in to Bilibili in the same browser profile. The userscript polls `http://127.0.0.1:5678/api/streak`; it does not store cookies or CSRF tokens in the tracker. The title limit in config is a guardrail and still needs confirmation against Bilibili's current account rules and update response.

## Checks

Run the unit suite, type checker, and offline recognition evaluator from the project environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pyrefly check
.\.venv\Scripts\python.exe .\tools\recognize_screenshots.py --dataset
.\.venv\Scripts\python.exe .\tools\recognize_screenshots.py --dataset --resolution 1920x1080
.\.venv\Scripts\python.exe .\tools\recognize_screenshots.py --dataset --resolution 2560x1440
```

`tools/extract_templates.py` remains the offline dataset asset builder and validator.

## Validation still required

The supplied screenshots establish offline recognition behavior, not live-game accuracy. Confirm capture against the actual game display mode, gather additional result captures for underrepresented outcomes and variants, and benchmark CPU, memory, and game frame-rate impact during a representative session. Verify the Bilibili endpoint fields, authentication/CSRF handling, response schema, and title restriction with the target account before relying on automatic title changes.
