---
repo_url: https://github.com/awbjcj/video-dedup
repo_name: video-dedup
role: sole author
generated_at: 2026-11-02
---

# Project: Video Dedup

A local tool for finding and reviewing duplicate or overlapping videos.

## Summary

Video Dedup scans video libraries for byte-identical files and visually similar footage, including clips contained in longer videos (`video_dedup.py`, `tests/test_video_dedup.py`). It combines a bounded candidate search with timeline matching and presents the results for terminal or browser review (`video_dedup.py`, `review-ui/src/App.tsx`). Users can save review plans and apply selected removals to a quarantine (`video_dedup.py`, `run_store.py`). The project is active and has one recorded Git author.

Role: sole author (18 of 18 commits through `0c41c93`; `git shortlog -sne 0c41c93`, `git rev-list --count 0c41c93`; implementation history: `git log -- video_dedup.py run_store.py review-ui/src tests`)
Repository: https://github.com/awbjcj/video-dedup
Timeline: 2026-08 – present (`git log --reverse --format=%as`, `git log -1 --format=%as`)

## Tech stack (evidence-backed)

- Python — scanner, command-line review, local server, and history storage (`video_dedup.py`, `run_store.py`).
- TypeScript — browser review state and components (`review-ui/src/`).
- JavaScript — browser smoke tests and frontend configuration (`review-ui/scripts/`, `review-ui/postcss.config.js`).
- HTML — browser application entry point and bundled review page (`review-ui/index.html`, `review-ui/bundle.html`).
- CSS — review interface styling (`review-ui/src/index.css`).
- React — browser review interface (`review-ui/src/App.tsx`, `review-ui/src/main.tsx`).
- Tailwind CSS — interface utilities and theme configuration (`review-ui/src/index.css`, `review-ui/tailwind.config.js`).
- SQLite — fingerprint, exact-hash, and failure cache (`video_dedup.py`).
- SQL — cache schema and parameterized queries (`video_dedup.py:FingerprintCache`).
- JSON — scan reports, saved plans, and review requests (`run_store.py:write_json`, `review-ui/src/lib/api.ts:savePlan`).
- FFmpeg — frame extraction and on-demand video previews (`video_dedup.py`).
- SHA-256 — identification of byte-identical files (`video_dedup.py`).
- unittest — Python test suite (`tests/`).
- Playwright — browser smoke scripts (`review-ui/scripts/browser-smoke.cjs`).
- Node.js — frontend unit-test runner (`review-ui/package.json`, `review-ui/src/lib/reviewDecisions.test.ts`).
- Vite — frontend development and build configuration (`review-ui/package.json`, `review-ui/vite.config.ts`).
- Parcel — generation of the self-contained browser bundle (`review-ui/package.json`, `review-ui/.parcelrc`).

## Architecture highlights

- Built a staged scanner that combines SHA-256 checks, a bounded keyframe-token index, and fixed-interval verification (`video_dedup.py`).
- Implemented whole-frame and regional perceptual hashes to match watermarked footage in test cases while rejecting low-information regions (`video_dedup.py`, `tests/test_watermarks.py`).
- Calculated directional timeline coverage for clips and compilations and used retained coverage to filter proposed removals (`video_dedup.py`, `tests/test_video_dedup.py`).
- Reused fingerprints, file hashes, and decode failures in a SQLite cache keyed by file metadata; corrupt fingerprint entries are discarded for recomputation (`video_dedup.py`, `tests/test_video_dedup.py`).
- Separated review plans from file operations; the command-line apply step checks file size and modification time, defaults to quarantine, and requires confirmation for permanent deletion unless explicitly bypassed (`video_dedup.py`).
- Synchronized decisions for files shared by overlapping review sets and excluded explicitly kept files from the removal list (`review-ui/src/lib/reviewDecisions.ts`, `review-ui/src/lib/reviewDecisions.test.ts`).
- Persisted scan history and named review plans with atomic JSON replacement and validated plan paths (`run_store.py`, `video_dedup.py`, `tests/test_run_history.py`).
- Built local browser previews that stream FFmpeg-transcoded video when a source format is not browser-native (`video_dedup.py`, `tests/test_video_dedup.py`).

## Quantified outcomes

- Added 73 Python test methods through `fec73ed` (`git grep -n -E '^[[:space:]]*def test_' fec73ed -- tests | Measure-Object -Line`).
- Added 8 frontend unit tests through `fec73ed` (`git grep -n -E '^[[:space:]]*(test|it)\(' fec73ed -- 'review-ui/src/lib/*.test.ts' | Measure-Object -Line`).
- Documented a local scan with 5,513 discovered files, 4,715 scanned files, and 183,489 candidate pairs; the underlying report and cache were local, while the summary is checked in (`docs/performance-research.md` at `fec73ed`).

## Skills demonstrated

### Languages

- Name: Python
  - Context: Built the scanner and persisted local review data.
  - Evidence:
    - Orchestrated candidate generation and detailed matching in the scan pipeline — `video_dedup.py:_scan`.
    - Wrote review data through a temporary file and atomic replacement — `run_store.py:write_json` (commit `f5c8246`).

- Name: TypeScript
  - Context: Implemented typed review decisions and browser requests.
  - Evidence:
    - Synchronized keeper choices across reviewed sets sharing a file — `review-ui/src/lib/reviewDecisions.ts:updateDecisions` (commit `ddde4cd`).
    - Typed response payloads and surfaced failed requests to the interface — `review-ui/src/lib/api.ts:requestJson`.

- Name: JavaScript
  - Context: Wrote browser smoke scripts for review operations and saved plans.
  - Evidence:
    - Started a local test server and exercised review operations — `review-ui/scripts/operations-smoke.cjs:main`.
    - Checked plan saving, renaming, and loading in the browser — `review-ui/scripts/history-smoke.cjs:main`.

- Name: HTML
  - Context: Used semantic elements and labels in the review interface.
  - Evidence:
    - Structured the review area with a main region, heading, and labeled navigation — `review-ui/src/components/ReviewWorkspace.tsx:116-158`.
    - Added a labeled video element with playback controls for each preview — `review-ui/src/components/FileCard.tsx:80-88`.

- Name: CSS
  - Context: Styled the interface and added keyboard and motion accommodations.
  - Evidence:
    - Defined a visible keyboard-focus outline — `review-ui/src/index.css:60-63`.
    - Reduced animation and transition durations when reduced motion is requested — `review-ui/src/index.css:94-102`.

### Frameworks

- Name: React
  - Context: Built a stateful review interface with undo and operation status.
  - Evidence:
    - Managed decision updates and undo history with a reducer — `review-ui/src/App.tsx:reviewReducer`.
    - Polled scan and removal status and refreshed the review session after operations — `review-ui/src/App.tsx:116-145`.

- Name: Tailwind CSS
  - Context: Applied responsive layout utilities and a shared color theme.
  - Evidence:
    - Changed the file-card grid across viewport sizes — `review-ui/src/components/ReviewWorkspace.tsx:255-261`.
    - Mapped theme colors to reusable custom properties — `review-ui/tailwind.config.js:8-43`.

### Databases

- Name: SQLite
  - Aliases: SQLite3
  - Context: Cached fingerprints, file hashes, and decoding failures for later scans.
  - Evidence:
    - Created cache tables and enabled write-ahead logging — `video_dedup.py:FingerprintCache.__init__`.
    - Evicted unreadable fingerprint entries so a later scan can recompute them — `video_dedup.py:FingerprintCache.get`.

- Name: SQL
  - Context: Defined cache keys and used parameterized reads and writes.
  - Evidence:
    - Defined composite keys for fingerprint records using file identity and sampling settings — `video_dedup.py:FingerprintCache.__init__`.
    - Stored decoding failures and looked up file hashes with bound parameters — `video_dedup.py:FingerprintCache.put_failure`, `video_dedup.py:FingerprintCache.get_file_hash`.

### Testing

- Name: unittest
  - Context: Wrote regression cases for persistence and safe file operations.
  - Evidence:
    - Verified a failed replacement leaves the existing saved data intact — `tests/test_run_history.py:RunHistoryTests.test_failed_atomic_replace_preserves_existing_json`.
    - Checked that permanent deletion refuses a changed retained file — `tests/test_web_operations.py:WebOperationTests.test_changed_keeper_is_refused_for_permanent_delete`.

- Name: Playwright
  - Context: Exercised browser review workflows and responsive layouts.
  - Evidence:
    - Checked review controls, accessible names, and desktop and mobile layouts — `review-ui/scripts/browser-smoke.cjs:main`.
    - Checked shared-file choices across review sets and after a page reload — `review-ui/scripts/shared-removal-smoke.cjs:checkRemoval`.

### Architecture

- Name: Perceptual hashing
  - Context: Compared video frames and regions to find visually similar footage.
  - Evidence:
    - Computed whole-frame and regional fingerprints for each sampled frame — `video_dedup.py:frame_sample`, `video_dedup.py:regional_frame_sample`.
    - Tested that moving obstructions survive candidate lookup and temporal matching — `tests/test_watermarks.py:RegionalFingerprintTests.test_moving_obstructions_survive_index_and_temporal_confirmation`.

- Name: SHA-256
  - Context: Identified exact duplicate candidates by hashing file contents.
  - Evidence:
    - Read files in chunks to compute a content digest — `video_dedup.py:file_sha256`.
    - Grouped same-size files by digest and reused cached hashes — `video_dedup.py:compute_exact_groups`.

- Name: Concurrency
  - Context: Parallelized extraction and prevented conflicting review mutations.
  - Evidence:
    - Ran detailed extraction in a worker pool while keeping cache access on the owner thread — `video_dedup.py:load_detailed_records`.
    - Rejected overlapping review mutations with a nonblocking operation lock — `video_dedup.py:exclusive_review_operation`.

- Name: API design
  - Context: Connected the local review interface to session, plan, and file operations.
  - Evidence:
    - Routed review requests and returned errors for invalid bodies or missing request headers — `video_dedup.py:3492-3548`.
    - Defined client calls for loading and renaming plans and applying reviewed decisions — `review-ui/src/lib/api.ts:66-82`.

### Tooling

- Name: FFmpeg
  - Context: Extracted frames for matching and generated browser-compatible previews.
  - Evidence:
    - Sampled keyframes and scaled them for the fast fingerprint pass — `video_dedup.py:extract_fast`.
    - Streamed a transcoded preview for sources that need conversion — `video_dedup.py:3358-3410`.

- Name: Node.js
  - Context: Ran frontend unit tests and controlled local browser-test fixtures.
  - Evidence:
    - Used the built-in test runner for the review decision tests — `review-ui/package.json:10`, `review-ui/src/lib/reviewDecisions.test.ts:1-16`.
    - Spawned and monitored the local fixture server for an operation smoke test — `review-ui/scripts/operations-smoke.cjs:38-49`.

- Name: Vite
  - Context: Configured the development and frontend build workflow.
  - Evidence:
    - Enabled the React plugin and mapped the source import alias — `review-ui/vite.config.ts:5-11`, `review-ui/src/lib/api.ts:1-11` (commit `a2eb1b2`).
    - Added development and build commands — `review-ui/package.json:6-8`.

- Name: Parcel
  - Context: Built a self-contained review page for the local server.
  - Evidence:
    - Bundled and inlined the page used by the server — `review-ui/package.json:9`, `video_dedup.py:3579-3581`.
    - Configured the resolver for source path aliases — `review-ui/.parcelrc:1-4`, `review-ui/tsconfig.json:10-14` (commit `a2eb1b2`).

- Name: JSON
  - Context: Stored reports and plans and exchanged review requests with the browser.
  - Evidence:
    - Serialized saved data to a temporary file before replacing the destination — `run_store.py:write_json`.
    - Serialized plan decisions in the browser request — `review-ui/src/lib/api.ts:savePlan`.
