# cudAI Recorder

A desktop recorder that captures computer-use demonstrations (screen video,
mouse, keyboard, active app/window and UI element context) for building
annotated datasets. Accepting the recording terms is mandatory on first launch
and cannot be withdrawn in the app. Nothing is recorded while paused, and
recordings cannot be deleted from the app; raw files are locked (macOS
`uchg`) once processed.

## What a recording contains

Recordings are stored per user in the app data directory
(macOS: `~/Library/Application Support/cudAI/recordings/<recording_id>/`).

| File | Contents |
| --- | --- |
| `manifest.json` | Start here. Task, environment, consent, video and clock info, file index, stats and how to interpret timestamps (schema `cudai.recording.v1`). |
| `timeline.jsonl` | Cleaned input events and active-window changes in time order, each with `t_video`, `frame` and `t_unix`. |
| `video.mp4` | Main display, H.264, constant 30 fps. Paused periods are black frames so video time stays linear. |
| `events.jsonl` | Raw input events (move, click, scroll, key press/release, pause/resume). |
| `top_window.jsonl` | Active app, bundle id / exe path, window title and bounds. |
| `element.jsonl` | Accessibility info for clicked UI elements. |
| `reduced_events_complete.jsonl`, `reduced_events_vis.jsonl`, `video_clips/` | Actions reduced from raw events (click, drag, type, hotkey, scroll) and a short clip per action, used by the annotation UI. |
| `metadata.json` | Full recorder-side metadata the manifest is built from. |

Timing: every timestamp is a monotonic clock reading in seconds. The video's
first frame is taken from the capture device's own timestamp (same clock), so
`video_time = t - video.video_start_timestamp` is exact to the frame. Input
coordinates are logical points; multiply by `display.scale_factor` for video
pixels.

### Privacy

Before anything is derived from a recording, `api/core/privacy.py` removes
personal and sensitive data from all recorded text (keystrokes, window
titles, page URLs, accessibility element text, task names) and replaces it
with typed placeholders, so the training signal survives:

| Placeholder | Removed |
| --- | --- |
| `[SECRET]` | passwords, tokens, API keys, private keys, credential URL parameters |
| `[EMAIL]` `[PHONE]` | contact details |
| `[CARD]` `[IBAN]` `[BANK_ACCOUNT]` | card (Luhn-checked) and bank numbers |
| `[AADHAAR]` `[PAN]` `[SSN]` `[PASSPORT]` | government ID numbers |
| `[IP]` `[MAC]` | network and device identifiers |

Typed values are redacted key by key (the physical key names are scrubbed
too). URLs keep their structure, query strings and fragments (app state such
as SAP Fiori routes and search terms). `manifest.json` → `privacy` records the
policy version and redaction counts. **The video is not redacted.** Older
recordings are redacted automatically on the next launch.

Keyboard events carry `name` (physical key, stable across modifiers), `char`
(what the OS produced), `text` (what the press contributed to typed text, if
any) and `modifiers`. The app's own shortcuts and input to the cudAI window are
excluded from the timeline and actions.

## Development

Requirements: macOS 12+ (Intel or Apple Silicon), Xcode command line tools,
Python 3.12, Node 22.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r recorder/api/requirements-dev.txt
cd recorder
scripts/build_ffmpeg_lgpl.sh   # LGPL FFmpeg for this Mac -> api/ffmpeg
npm ci
npm start                      # Electron + Python backend
CUDAI_DEVTOOLS=1 npm start     # same, with the Chromium inspector open
```

Grant Screen Recording, Accessibility and Input Monitoring to the app (or to
your terminal when running from source); cudAI checks them before recording.

### Tests

```bash
cd recorder
npm test                       # backend tests + frontend type-check

cd api
python -m pytest tests                              # backend only
CUDAI_E2E=1 python -m pytest tests/test_e2e_recording.py   # records your screen
```

CI (`.github/workflows/ci.yml`) runs lint, backend tests (with the LGPL FFmpeg
build) and the frontend type-check on every push.

`tests/test_reducer_golden.py` fingerprints the extracted actions for a
synthetic recording. If you change how actions are extracted on purpose,
inspect the new output and update the expected fingerprint.

Set `CUDAI_DATA_DIR` to use a different data directory (tests do this
automatically; legacy-folder migration is skipped when it is set).

Global shortcuts: ⌘⌥R start, ⌘⌥P pause/resume, ⌘⌥T stop (Ctrl+Alt on
Windows).

## Packaging

```bash
cd recorder
scripts/build_ffmpeg_lgpl.sh universal   # x86_64 + arm64 FFmpeg
npm run build-flask                      # PyInstaller backend
npm run make
```

The bundled FFmpeg is an LGPL-2.1 build with no GPL/nonfree components; H.264
is encoded by Apple VideoToolbox. The license and source notice ship in
`api/licenses/`.

## Attribution

cudAI is derived from [AgentNetTool](https://github.com/xlang-ai/AgentNetTool)
(OpenCUA), itself built on [DuckTrack](https://github.com/TheDuckAI/DuckTrack)
and [OpenAdapt](https://github.com/OpenAdaptAI/OpenAdapt). AgentNetTool is
released under the MIT License; its copyright notice is retained in
[LICENSE](LICENSE) and must be included with any distribution.
