---
repo_url: https://github.com/awbjcj/video-dedup
repo_name: video-dedup
role: sole author
generated_at: 2026-10-31
---

# Project: Video Dedup

A local tool for finding and reviewing duplicate or overlapping videos.

## Summary

Video Dedup scans video libraries for byte-identical files and visually similar footage, including clips contained in longer videos (`video_dedup.py`, `tests/test_video_dedup.py`). It combines a bounded candidate search with timeline matching and presents the results for terminal or browser review (`video_dedup.py`, `review-ui/src/App.tsx`). Users can save review plans and apply selected removals to a quarantine (`video_dedup.py`, `run_store.py`). The project is active and has one recorded Git author.

Role: sole author (17 of 17 commits through `fec73ed`; `git shortlog -sne fec73ed`, `git rev-list --count fec73ed`)
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

Languages: Python, TypeScript, JavaScript, HTML, CSS
Frameworks: React, Tailwind CSS
Databases: SQLite (aliases: SQLite3)
Testing: unittest, Playwright
Architecture: Perceptual hashing, SHA-256, Concurrency, API design
Tooling: FFmpeg, Node.js, Vite, Parcel
