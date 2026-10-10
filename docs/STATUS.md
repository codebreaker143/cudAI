# cudAI Recorder — Progress Status

_Last updated: 2026-10-11 · branch `xrec-native-capture`_

cudAI is a macOS desktop app that records people doing real work (screen,
mouse, keyboard, apps, UI elements) and packages it as training data for AI
models that operate computers.

## Original plan and where we are

| # | Step | Status | Notes |
|---|---|---|---|
| 1 | Stabilize local recorder | ✅ Done | Watchdog stops capture if the app dies; crash recovery on next launch; permission checks; disk-space guard; verified with a 35-min real recording |
| 2 | Remove AgentNet/OBS/cloud legacy code | ✅ Done | Cloud, login, TaskHub, review/verify, OBS and GPL FFmpeg removed; folder renamed to `recorder/`; ~5,000 lines of dead code removed |
| 3 | Standardize recording schema | ✅ Done | `cudai.recording.v1`: `manifest.json` + `timeline.jsonl` with video time, frame and wall-clock time per event |
| 4 | Fix event/video timestamp alignment | ✅ Done | Frame-exact (taken from the capture device's first frame); verified over 35 min, including across system sleep |
| 5 | Fix keyboard + reducer data quality | ✅ Done | Stable key names (⌘/⌥ bug fixed), typed text, shortcuts; app's own hotkeys and window excluded; regression test on reducer output |
| 6 | Pause/resume + chunking | ✅ Done | Pause/resume (also automatic on sleep and screen lock). Video written as 10-second chunks (exactly 300 frames); frames after a pause are cut before upload; a crash loses at most the last chunk |
| 7 | Cloud upload | 🟡 Built, needs a server | Live upload of redacted video chunks + OCR layer + redacted events, resumable after network loss and restarts, final files after processing. Reference ingest server (local or any S3-compatible storage) and GPU second-pass worker in `server/`. Next: deploy the server and pick the storage provider |
| 8 | Build Mac installer | 🟡 Partly done | Packaged backend builds (358 MB with on-device OCR) and the redaction worker runs inside it. Must be rebuilt with a native arm64 Python (current builds are Intel-only, see below). `.dmg` not produced yet |
| 9 | Windows version | ⏳ Not started | Capture, encoder and installer to be built |
| 10 | Signing, permissions, onboarding, release testing | 🟡 Partly done | Permission onboarding and mandatory consent done. Signing and notarization wait on the Apple Developer ID |

## Added along the way

- **Data richness:** clicked UI element labels, including inside Chrome/Electron
  web apps (Fiori, Workday); browser page URLs (with app state); active
  app/window titles; one video per display at native resolution.
- **Privacy (on the Mac, before upload):** one Microsoft Presidio rule set
  (`privacy/cudai_privacy`, shared with the server) removes passwords,
  tokens, emails, phones, cards, bank and government IDs and IP/MAC
  addresses. In text they become `[EMAIL_ADDRESS]`-style placeholders; in
  the video, PaddleOCR (PP-OCR models on ONNX Runtime) reads each chunk and
  OpenCV covers the values with solid boxes. Only redacted chunks are
  uploaded.
- **OCR content layer:** every chunk ships with its on-screen text and boxes
  (`ocr/<chunk>.jsonl`), sensitive values replaced.
- **Server second pass:** GLiNER + PaddleOCR on GPU remove people's names
  into `clean/`, count anything the device missed, and delete the raw upload
  after 72 h; QA tool for human spot checks of the name miss rate.
- **Pipeline timing:** every step from capture to cloud is timed and shown in
  the review screen.
- **Consent and integrity:** mandatory, versioned consent stored with each
  recording; no in-app deletion; raw files locked after processing.
- **Licensing:** LGPL-only FFmpeg with Apple's hardware encoder; no GPL
  exposure.
- **Security:** local API reachable only from the app (localhost +
  per-launch token).
- **Review UI:** video player with timeline, action markers and click
  overlay; actions/events/details panels in sync; task naming; sub-task
  splitting.
- **Engineering:** 116 automated tests, opt-in real screen-recording tests,
  CI on every push (Apple Silicon), pinned dependencies and lockfile.

## Verified on real usage

- 34.7-minute recording: 46k events → 1,087 actions, processed in 1.9 s;
  cursor matched recorded clicks exactly at 0.5, 12 and 30 min.
- 4-hour synthetic load: processed in about 5 s, 531 MB peak memory.
- Live upload with real capture: first 10-second chunk (300 frames) reached
  the server mid-recording; after stop the server-rebuilt video matched the
  local `video.mp4` frame for frame.
- Video at native resolution (3024×1964 on a MacBook), 30 fps, about
  460 MB/hour.
- On-device redaction with real capture (M3 Pro, Intel build under
  Rosetta): an active 10-second chunk took 19.7 s (8 OCR passes: OCR 18.0 s,
  Presidio 1.1 s); capture to cloud 28.8 s. Synthetic test: email and card
  number masked from the frame they appear, business data (PO and invoice
  numbers) kept.

## Open items, in priority order

1. **Deploy the ingest server** (pick AWS S3, Cloudflare R2 or GCS; HTTPS
   domain) and the GPU second-pass worker; issue access keys.
2. **Native arm64 build**: the dev Python (pyenv 3.12.2) is Intel, so the
   app and all timings so far ran under Rosetta, and the first launch of a
   new build stalls for minutes while macOS translates OpenCV. Release builds
   need a native arm64 or universal2 Python 3.12.
3. **Unsigned internal installer (`.dmg`)** for pilot contributors, with the
   server address preset.
4. **Contributor accounts and task assignment** (replace shared access keys).
5. **Quality review and buyer export pipeline.**
6. **Legal review** of terms, consent withdrawal (India DPDP Act) and buyer
   licensing.
7. **Windows version.**
8. **Signing, notarization and auto-update** once the Developer ID arrives.

## Needs verification

- **Server second pass on a GPU machine.** Tested with the app's CPU OCR and a
  stub name detector; real GLiNER and GPU PaddleOCR have not run yet.
- **On-device redaction speed on a native arm64 build** (expected faster than
  the Rosetta numbers above).
- **Multi-display capture on real hardware.** It is implemented and
  unit-tested, but needs a second, non-mirrored monitor. Run:
  `CUDAI_E2E=1 python -m pytest tests/test_e2e_recording.py` (from
  `recorder/api`).

## Known limitations

- Video redaction only covers text OCR can read. Text that appears and
  disappears between OCR passes (at most 2 per second on the Mac), very small
  or stylised text, and images of documents can be missed. People's names
  are only removed on the server. Contributors are told to pause for private
  information.
- On-device OCR is CPU-heavy: during busy screen activity redaction falls
  behind live (about 2× real time under Rosetta) and uploads catch up later.
- Redaction is pattern-based. Any 10-digit number starting with 6–9 is
  treated as a phone number, and detection can miss unusual formats, so a
  human or legal review before sale is still advised.
- Only macOS is supported. Mirrored displays are not captured separately.
- `CONTACT_EMAIL` in the terms is still blank.
