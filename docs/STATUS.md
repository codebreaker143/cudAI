# cudAI Recorder — Progress Status

_Last updated: 2026-10-09 · branch `xrec-native-capture` · CI green_

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
| 6 | Pause/resume + chunking | 🟡 Partly done | Pause/resume done (also automatic on sleep and screen lock). 10-second chunking moves to step 7 |
| 7 | Cloud upload | ⏳ Not started | Design ready: 10-second chunks, resumable upload queue, pre-signed URLs. Needs a decision on cloud provider and backend |
| 8 | Build Mac installer | 🟡 Partly done | Packaged backend builds (57 MB) and works; universal FFmpeg built. `.dmg` not produced yet |
| 9 | Windows version | ⏳ Not started | Capture, encoder and installer to be built |
| 10 | Signing, permissions, onboarding, release testing | 🟡 Partly done | Permission onboarding and mandatory consent done. Signing and notarization wait on the Apple Developer ID |

## Added along the way

- **Data richness:** clicked UI element labels, including inside Chrome/Electron
  web apps (Fiori, Workday); browser page URLs (with app state); active
  app/window titles; one video per display at native resolution.
- **Privacy:** passwords, tokens, emails, phones, cards, bank and government
  IDs, and IP/MAC addresses are removed from all recorded text and replaced
  with labels such as `[EMAIL]`. Existing recordings are cleaned on launch.
  The video is not redacted.
- **Consent and integrity:** mandatory, versioned consent stored with each
  recording; no in-app deletion; raw files locked after processing.
- **Licensing:** LGPL-only FFmpeg with Apple's hardware encoder; no GPL
  exposure.
- **Security:** local API reachable only from the app (localhost +
  per-launch token).
- **Review UI:** video player with timeline, action markers and click
  overlay; actions/events/details panels in sync; task naming; sub-task
  splitting.
- **Engineering:** 90 automated tests, opt-in real screen-recording tests,
  CI on every push (Apple Silicon), pinned dependencies and lockfile.

## Verified on real usage

- 34.7-minute recording: 46k events → 1,087 actions, processed in 1.9 s;
  cursor matched recorded clicks exactly at 0.5, 12 and 30 min.
- 4-hour synthetic load: processed in about 5 s, 531 MB peak memory.
- Video at native resolution (3024×1964 on a MacBook), 30 fps, about
  460 MB/hour.

## Open items, in priority order

1. **Unsigned internal installer (`.dmg`)** for pilot contributors.
2. **Cloud upload** in 10-second chunks with a secure server (provider and
   backend decision needed).
3. **Contributor accounts and task assignment.**
4. **Quality review and buyer export pipeline.**
5. **Video privacy:** detect and blur sensitive text in the video.
6. **Legal review** of terms, consent withdrawal (India DPDP Act) and buyer
   licensing.
7. **Windows version.**
8. **Signing, notarization and auto-update** once the Developer ID arrives.

## Needs verification

- **Multi-display capture on real hardware.** It is implemented and
  unit-tested, but needs a second, non-mirrored monitor. Run:
  `CUDAI_E2E=1 python -m pytest tests/test_e2e_recording.py` (from
  `recorder/api`).

## Known limitations

- The video is not redacted; contributors are told to pause for sensitive
  data.
- Text redaction is pattern-based. Any 10-digit number starting with 6–9 is
  treated as a phone number, and detection can miss unusual formats, so a
  human or legal review before sale is still advised.
- Only macOS is supported. Mirrored displays are not captured separately.
- `CONTACT_EMAIL` in the terms is still blank.
