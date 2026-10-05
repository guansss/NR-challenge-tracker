# Nightreign Challenge Tracker

Windows desktop HUD and game session tracker for Nightreign winning streak challenges.

## Run

From the repository root, install dependencies into the project virtual environment and launch the app:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.main
```

## Build a portable Windows package

Build on Windows using the project's virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe .\tools\build_release.py
```

The project version is set in `pyproject.toml`; the build script creates
`dist\Nightreign-Challenge-Tracker-v<version>-windows.zip`.

This uses PyInstaller's one-file mode: the executable contains Python, its
dependencies, and the runtime assets. Distribute the ZIP and extract both files
into a writable folder before running `Nightreign Challenge Tracker.exe`.
Python is not required on the target PC. `config.yaml` remains editable, and
`history.yaml` and `state.json` are created or updated
beside the executable. The package omits the offline screenshot dataset.

## GitHub releases

Pushing a version tag matching the version in `pyproject.toml` automatically
builds the Windows package and publishes it as a GitHub Release. For example,
with version `0.1.0`, push the `v0.1.0` tag:

```powershell
git tag v0.1.0
git push origin v0.1.0
```

Download the `Nightreign-Challenge-Tracker-v0.1.0-windows.zip` asset from that
release's Assets section.

The application captures only a visible window whose title contains `capture.target_window` from `config.yaml`. Keep Nightreign in a supported window-capture mode. If capture is unavailable, the app preserves any attempt as interrupted rather than recording a loss.

Session history is stored in `history.yaml` at the project root. HUD geometry and desired-title revision/sync status are stored together in the adjacent `state.json`.

Accepted preparation and result screens are also saved as annotated PNGs under `debug/screenshots/`. Filenames include the 1-based attempt number and recognized identity; an existing file for the same identity is left unchanged.

## Configuration

Set `language` in `config.yaml` to `auto`, `en`, or `zh`. With `auto`, the app checks the system's preferred UI languages in order and uses the first supported language; if neither English nor Chinese is listed, it falls back to English. UI translations are grouped by feature in `assets/translations.yaml`.

Recognition ROIs, confidence thresholds, and sampling intervals are configured separately in `config.yaml`; the supplied values are starting points calibrated against the included 2560x1440 screenshot set. The app validates runtime settings and binds the local API only to a loopback address.

For Bilibili title updates, install `app/integrations/bilibili.user.js` in Tampermonkey and open Bilibili's live-center page (`https://link.bilibili.com/p/center/index#/my-room/start-live`) while signed in to the account whose room title should change. The userscript polls the local tracker at `http://127.0.0.1:5678/api/streak` and updates the title by manipulating the page's room-title editor. Ensure the correct account and room are open. The configured title limit is a guardrail; confirm that the generated title is accepted by the target account.

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

The supplied screenshots establish offline recognition behavior, not live-game accuracy. Confirm capture against the actual game display mode, gather additional result captures for underrepresented outcomes and variants, and benchmark CPU, memory, and game frame-rate impact during a representative session. Before relying on automatic Bilibili title updates, confirm the userscript can find and save the room-title editor on the live-center page and that the target account accepts the generated title.
