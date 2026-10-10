# cudAI ingest server

Receives recordings from the cudAI desktop app **while they are being
recorded**. This is a reference implementation: small, dependency-light and
storage-agnostic. Contributor accounts and task assignment come later; for now
each app is given an access key.

## Run it

```bash
cd server
pip install -r requirements.txt

# Development: files kept in ./data, upload links served by this server
CUDAI_API_KEYS=dev-key python -m cudai_ingest --port 8080

# Production: any S3-compatible bucket (the app uploads straight to it)
CUDAI_API_KEYS=key1,key2 CUDAI_STORAGE=s3 CUDAI_S3_BUCKET=cudai-recordings \
CUDAI_S3_REGION=ap-south-1 AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
gunicorn -w 4 -b 0.0.0.0:8080 'cudai_ingest.app:create_app()'
```

| Provider | Settings |
|---|---|
| AWS S3 | `CUDAI_S3_REGION` (e.g. `ap-south-1`), AWS credentials |
| Cloudflare R2 | `CUDAI_S3_ENDPOINT=https://<account>.r2.cloudflarestorage.com`, `CUDAI_S3_REGION=auto`, R2 API token as AWS credentials |
| Google Cloud Storage | `CUDAI_S3_ENDPOINT=https://storage.googleapis.com`, HMAC interoperability keys as AWS credentials |
| MinIO | `CUDAI_S3_ENDPOINT=http://minio:9000`, MinIO keys |

The bucket must allow `PUT` from the app (no browser CORS needed, since the app
is not a web page). Serve the API over HTTPS; the app refuses plain `http://`
except for `localhost`.

In the app: **Settings › Cloud upload** → server address and access key. For
builds handed to pilot contributors, set `CUDAI_UPLOAD_URL` and
`CUDAI_UPLOAD_KEY` in the app's environment instead.

## What arrives

```
recordings/<recording id>/
  _recording.json                 status (receiving | complete), contributor, consent version
  _files.json                     every file with size and SHA-256 (written on complete)
  chunks/display_0/segment_000/chunk_00000.mp4   10-second video chunks, 300 frames each
  chunks/display_0/gap_001.mp4    black frames covering a pause
  live/events/000001.jsonl        input events, uploaded every 10 s (redacted)
  live/top_window/…, live/element/…
  metadata.json, manifest.json, timeline.jsonl, events.jsonl,
  reduced_events_*.jsonl, task_name.json, …   final files (after processing)
```

Text and video are redacted on the contributor's computer before upload
(passwords, tokens, emails, phone, card, bank and ID numbers, IP/MAC
addresses): text values become placeholders, and text recognised on screen
is covered with solid boxes. Frames captured after the contributor presses
pause are cut before the chunk is uploaded. Each chunk comes with its OCR
layer (`ocr/<chunk>.jsonl`).

Rebuild a recording's redacted videos from `clean/`:

```bash
python -m cudai_ingest.assemble <recording id> ./out
```

It joins each display's `video.parts` from `metadata.json` with FFmpeg
(stream copy when every part was encoded on the device).

## Second pass: names, checks, retention

Recordings arrive already redacted on the contributor's Mac (text and video,
same Presidio rules as `privacy/cudai_privacy`). They still contain people's
names, so `recordings/` is **sensitive**:

- **Encrypt the bucket** (S3 default encryption with SSE-KMS; R2 and GCS
  encrypt at rest by default).
- **Split access**: the ingest API only signs upload links; the worker role
  reads `recordings/` and writes `clean/`; export and annotation roles read
  `clean/` only. Nothing trains on or exports from `recordings/`.

The worker (GPU) produces `clean/<id>/`:

```bash
pip install -r requirements-worker.txt   # PaddleOCR + GLiNER on GPU, full FFmpeg on PATH
python -m cudai_ingest.worker            # loops; --once for a single pass
```

- **Video**: PaddleOCR (PP-OCRv5 server, GPU) reads every chunk; names found
  by GLiNER (`CUDAI_NAME_MODEL`, default `urchade/gliner_multi_pii-v1`, good
  on Indian names and fragmented UI text) are covered with solid boxes.
- **Text**: keystrokes (run by run), window titles, element labels, action
  descriptions, task names and the OCR layer get the same detector; names
  become `[PERSON]`.
- **`_qa.json`**: names removed, and **device misses**: values the
  on-device rules should have caught (target: zero).
- **`_timings.json`**: seconds per step.
- **Retention**: `recordings/<id>/` is deleted `CUDAI_RAW_RETENTION_HOURS`
  (default 72) after its clean copy exists.

**Measure misses** with human spot checks:

```bash
python -m cudai_ingest.qa sample --n 50 --out review/   # random clean frames + review.csv
python -m cudai_ingest.qa report review/review.csv      # miss rate
```

If names get through often, or buyers want device-side guarantees, move name
removal onto the Mac with a small quantized GLiNER.

## Protocol

All API calls send `Authorization: Bearer <access key>` and JSON.

| Call | Body | Response |
|---|---|---|
| `PUT /v1/recordings/{id}` | `contributor_id`, `consent_version`, `recorder_version`, `schema_version`, `started_at` | the recording record |
| `POST /v1/recordings/{id}/files` | `path`, `size`, `sha256` | `{"exists": true}`, or an upload link `{"method": "PUT", "url", "headers"}` |
| `PUT <url>` | the file bytes, with the given headers | 200 |
| `POST /v1/recordings/{id}/complete` | `files: [{path, size, sha256}]` | the record (`status: complete`), or 409 with `missing: [...]` |

- Recording ids are UUIDs. A recording belongs to the access key that opened
  it; other keys get 403.
- Paths are relative, without `..`; names starting with `_` are reserved.
- The same path can be uploaded again (e.g. after the contributor edits a task
  name); the latest content wins. `complete` can be called again after that.
- The app retries with backoff and resumes after restarts, so every call must
  be idempotent.
