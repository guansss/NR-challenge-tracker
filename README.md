# Nightreign Challenge Tracker

Nightreign Challenge Tracker is a small Windows desktop HUD that recognizes
game screens to record Nightreign runs and track challenges and streaks.

It runs image recognition on captured game window and does not interact
with game memory or modify game files, so it is not expected to affect the
game's anti-cheat.

<p align="center"><img src="docs/hud.png" alt="Nightreign Challenge Tracker HUD"></p>

## Install

1. Open the [latest GitHub release](https://github.com/guansss/NR-challenge-tracker/releases/latest).
2. Download `Nightreign-Challenge-Tracker-...-windows.zip` from the release's
   **Assets**.
3. Extract the zip.
4. Double-click **Nightreign Challenge Tracker.exe**.
5. Start Nightreign and play the game as usual.

The HUD stays above other windows. Drag it to move it or use the corner grip to
resize it.

## Use the tracker

The tracker watches for preparation and result screens and records recognized
runs automatically.

IMPORTANT: On the result screen (you'll hear a "ding" sound), scale the map
to its minimum size so the Nightlord icon is fully visible for recognition. Live recognition results
are shown in the HUD.

![Nightreign result screen](docs/result-screen.jpg)

- **Pause / Resume** stops or resumes game monitoring.
- To fix a missed or incorrect run, select it in recent runs and choose
  **Resolve**. Review the character, boss, variant, outcome, and times, then
  save the correction.
- In **Settings**, select an **Active Challenge** or choose **Manage
  Challenges...** to create, edit, and delete Challenges. A **Normal** Challenge
  counts included sessions and victories. A **Winning Streak** Challenge has an
  eligible Nightfarer (or **Any Nightfarer**) and a goal. **Any Nightfarer**
  counts completed runs across all characters, including runs with an unknown
  character. Excluding a session affects that Challenge's analysis, not run
  history.
- **Lock** lets mouse clicks pass through the HUD. Press **Ctrl+Shift+L**
  to unlock it.
- Close the HUD with **×** when finished. Run history is saved automatically.

## Optional: sync your Bilibili live-room title

Title syncing uses a userscript and requires a userscript manager to be installed in your browser. The feature also requires the tracker's local API server to be enabled.

1. Ensure your browser has a userscript manager installed, for example, Tampermonkey.
2. Start the tracker, open **Settings**, and click the userscript URL in the
   **Bilibili** section. If you have the local API server disabled, the URL will not show up, and you will need to enable the local API server and restart the tracker.
3. Your browser's userscript manager will then show an
   installation page. Follow the prompts to install the script. If you change
   the local API server's host or port, install the script again.
4. Go to [Bilibili live center](https://link.bilibili.com/p/center/index#/my-room/start-live).
   The userscript will then automatically update your live-room title based on the tracker.
   Keep the live-center tab in the foreground, because the browser may suspend updates from a background tab.

Check the HUD's **Title sync** status and verify the result. Change the title
template in **Settings**. Values not used by the active Challenge are `0`.

| Placeholder | Normal Challenge | Winning Streak Challenge |
| --- | --- | --- |
| `{wins}` | Included victories | `0` |
| `{total}` | Included sessions | `0` |
| `{streak}` | `0` | Current streak |
| `{goal}` | `0` | Streak target |

For example: `Nightreign Winning Streak {streak}/{goal}`.

## Files, settings, and updates

The tracker stores files beside the executable:

- `history.yaml` — run history.
- `user-config.yaml` — settings, including Challenges.
- `state.json` — HUD size and position.

These files are local to the extracted folder. Before updating, close the
tracker and back up these files. Extract the new release into the same folder
and keep your existing files.

Debug screenshots are off by default; enable them in **Settings**
to save captures under `debug/screenshots` beside the executable.

## Troubleshooting

- **The game window is unavailable:** Make sure Nightreign is running, visible,
  and not minimized.
- **Screens are not recognized:** Keep the game visible. On result screens,
  scale the map to its minimum size and check the recognition result in the HUD.
- **A run has the wrong character, boss, or outcome:** Select it in recent runs
  and choose **Resolve**.
- **Bilibili title syncing is not working:** Make sure the tracker is running, the userscript is activated in the userscript manager, and the live-center tab is open in the foreground.

## Game language support

Automatic game-screen recognition currently supports the Chinese version of
Nightreign. To use another game language, provide your own result-screen
screenshots and regenerate the recognition templates from source. This
advanced setup is not available in the portable app.

Put `.jpg` screenshots in `assets/dataset/result-screens`. Include:

- At least one result screenshot for every Nightlord and every Everdark
  variant.
- At least one of each result: first day, second day, final day, and final-day
  victory.
- The regular map (not the Great Hollow map), with the map at minimum size and
  the cursor out of the way.
- Filenames in the format
  `<nightlord>[-everdark]_<day1|day2|day3|victory>.jpg`, such as
  `adel_day1.jpg` or `adel-everdark_victory.jpg`.

From the project root, regenerate the templates using the project's virtual
environment:

```powershell
.\.venv\Scripts\python.exe .\tools\extract_templates.py
```

## Development

Development and release builds require Windows and Python 3.12 or later. From
the project root, create a virtual environment, install dependencies, and run
the app:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt
.\.venv\Scripts\python.exe -m app.main
```

Build the portable release with:

```powershell
.\.venv\Scripts\python.exe .\tools\build_release.py
```

The versioned ZIP is created in `dist`; the version is set in `pyproject.toml`.
A GitHub Release is published automatically when a matching `v<version>` tag
is pushed.

Run the tests, type checker, and offline recognition evaluator with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pyrefly check
.\.venv\Scripts\python.exe .\tools\recognize_screenshots.py --dataset
```
