# cudAI Recorder

A desktop recorder that captures computer-use demonstrations (screen video,
mouse, keyboard, active app/window and UI element context) for building
annotated datasets. Accepting the recording terms is mandatory on first launch
and cannot be withdrawn in the app. Nothing is recorded while paused, and
recordings cannot be deleted from the app; raw files are locked (macOS
`uchg`) once processed.

Current progress and roadmap: [docs/STATUS.md](docs/STATUS.md).

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

Redaction rules live in one package, [privacy/cudai_privacy](privacy/), built
on **Microsoft Presidio** and shared by the app and the ingest server.
Sensitive values are replaced with Presidio entity names, so the training
signal survives:

| Placeholder | Removed |
| --- | --- |
| `[SECRET]` | passwords, tokens, API keys, private keys, credential URL parameters |
| `[EMAIL_ADDRESS]` `[PHONE_NUMBER]` | contact details |
| `[CREDIT_CARD]` `[IBAN_CODE]` `[BANK_ACCOUNT]` | card (Luhn-checked) and bank numbers |
| `[IN_AADHAAR]` `[IN_PAN]` `[US_SSN]` `[PASSPORT]` | government ID numbers |
| `[IP_ADDRESS]` `[MAC_ADDRESS]` | network and device identifiers |
| `[PERSON]` | people's names (server second pass only, GLiNER) |

On the contributor's Mac, before anything is uploaded:

- **Text** (keystrokes, window titles, page URLs, element text, task names):
  values are replaced by placeholders. Typed values are redacted key by key,
  physical key names included. URLs keep their structure, queries and
  fragments.
- **Video** (`api/core/redaction.py`, `cudai_privacy/video.py`): each
  10-second chunk is OCR'd with PaddleOCR's PP-OCR models on ONNX Runtime
  (RapidOCR), in a low-priority worker process. OpenCV change detection
  OCRs only frames, and regions, that changed. Values the rules find are
  covered with solid OpenCV rectangles from the first frame they could
  appear, and the chunk is re-encoded. Chunks with nothing to mask are not
  touched.
- Each chunk also gets an **OCR content layer** (`ocr/<chunk>.jsonl`): text
  lines with boxes, sensitive values replaced, and the masked boxes.

The local `video.mp4` stays original. The server then removes people's names
(see [server/README.md](server/README.md)). `manifest.json` → `privacy`
records the rule version, text redaction counts and the video redaction
summary. Automatic detection can miss things; contributors are told to pause
for private information.

### Cloud upload

New recordings upload automatically while they are recorded
(`api/core/upload.py`), to the cudAI ingest server in [server/](server/)
(any S3-compatible storage):

- **Video** is written as standalone 10-second MP4 chunks
  (`chunks/display_N/segment_SSS/chunk_CCCCC.mp4`, 300 frames each), each
  uploaded once it is closed **and redacted**; an unredacted chunk is never
  uploaded. Frames captured after the contributor
  presses pause are cut before the chunk leaves the computer. A crash or
  power loss loses at most the last chunk.
- **Events** are uploaded every 10 s, redacted first; a typing run still in
  progress waits for the next upload so values typed across a boundary are
  still caught.
- **After processing**, the final files go up and the recording is marked
  complete; local chunks are then deleted (`video.mp4` stays). The server
  rebuilds identical videos from `video.parts` in `metadata.json`.

Every step, from capture through each redaction tool to the upload, is
timed in `pipeline_timings.jsonl` (`api/core/timing.py`). The review screen's
**Pipeline timing** section shows per-step medians and capture-to-cloud lag.

Progress is kept in `upload_state.json` per recording, so uploads resume after
network loss or a restart. Recordings made under terms before
`CLOUD_UPLOAD_CONSENT_VERSION` (`api/core/consent.py`) are never uploaded.
Configure in **Settings › Cloud upload**, or with `CUDAI_UPLOAD_URL` and
`CUDAI_UPLOAD_KEY`.

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
