---
repo_url: https://github.com/awbjcj/video-dedup
repo_name: video-dedup
role: sole author
generated_at: 2026-11-04
---

# Project: Video Dedup

A local tool for finding and reviewing duplicate or overlapping videos.

## Summary

Video Dedup helps people find and review byte-identical videos and visually similar footage, including clips contained in longer videos (`video_dedup.py:_scan`, `tests/test_video_dedup.py:FingerprintTests.test_directional_coverage_for_contained_clip`). It uses a bounded candidate search and timeline matching, then presents results for terminal or browser review (`video_dedup.py:build_candidates`, `video_dedup.py:detailed_match`, `review-ui/src/App.tsx:reviewReducer`). Reviewers can save plans and apply selected removals to quarantine (`run_store.py:write_json`, `video_dedup.py:WebReviewState._apply_reviewed`). The project is active; its recorded implementation history has one author.

Role: sole author (19 of 19 recorded commits through `2b715dc`; `git shortlog -sne 2b715dc`, `git rev-list --count 2b715dc`; implementation history: `git log -- video_dedup.py run_store.py review-ui/src tests`)
Repository: https://github.com/awbjcj/video-dedup
Timeline: 2026-08 – present (`git log --reverse --format=%as`, `git log -1 --format=%as`)
Project context: unknown

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
- cProfile — local call-path profiling documented in `docs/performance-research.md:80-86` (commit `fec73ed`).

## Architecture highlights

- Built a staged scanner that checks SHA-256 digests, ranks a bounded keyframe-token index, and verifies likely pairs at fixed intervals (`video_dedup.py:compute_exact_groups`, `video_dedup.py:build_candidates`, `video_dedup.py:detailed_match`).
- Matched watermarked footage in regression cases by combining whole-frame and regional perceptual hashes while excluding uninformative regions (`video_dedup.py:sample_distance`, `tests/test_watermarks.py:RegionalFingerprintTests.test_moving_obstructions_survive_index_and_temporal_confirmation`; commit `6c71cf0`).
- Calculated directional timeline coverage so a contained clip and its compilation can have different covered percentages (`video_dedup.py:detailed_match`, `tests/test_video_dedup.py:FingerprintTests.test_directional_coverage_for_contained_clip`).
- Split review groups at disjoint clips in a shared compilation while carrying exact-copy aliases into each relevant group (`video_dedup.py:connected_components`, `tests/test_video_dedup.py:FingerprintTests.test_exact_aliases_are_repeated_across_disjoint_clip_groups`; commit `a5eead7`).
- Preferred retaining a compilation when its parts are fully covered, then checked each proposed removal against the remaining keepers (`video_dedup.py:automatic_removal_order`, `tests/test_video_dedup.py:FingerprintTests.test_covering_strategy_prefers_compilation_over_higher_quality_parts`; commit `fec73ed`).
- Reused fingerprints, exact hashes, and decoding failures through a SQLite cache keyed by file metadata; corrupt fingerprint entries are evicted for recomputation (`video_dedup.py:FingerprintCache`, `tests/test_video_dedup.py:FingerprintTests.test_cache_discards_a_corrupt_fingerprint_row`).
- Separated review plans from file operations; command-line apply checks file size and modification time, defaults to quarantine, and requires confirmation for permanent deletion unless explicitly bypassed (`video_dedup.py:apply_plan`).
- Rechecked both the removal target and its covering files before permanent browser deletion, refusing changed files (`video_dedup.py:WebReviewState._apply_reviewed`, `tests/test_web_operations.py:WebOperationTests.test_changed_keeper_is_refused_for_permanent_delete`; commit `f5c8246`).
- Synchronized decisions for files shared by overlapping review sets and excluded explicit keepers from the removal list (`review-ui/src/lib/reviewDecisions.ts:updateDecisions`, `review-ui/src/lib/reviewDecisions.ts:removalFiles`; commit `ddde4cd`).
- Persisted scan history and named plans with atomic JSON replacement and constrained saved-plan paths (`run_store.py:write_json`, `run_store.py:plan_path`, `tests/test_run_history.py:RunHistoryTests.test_failed_atomic_replace_preserves_existing_json`; commit `f5c8246`).
- Prevented concurrent review mutations while allowing operation progress to be read (`video_dedup.py:exclusive_review_operation`, `tests/test_web_operations.py:WebOperationTests.test_progress_is_readable_during_quarantine_and_mutations_rejected`; commit `f5c8246`).
- Built a local review server with byte-range video delivery and on-demand FFmpeg previews for unsupported source formats (`video_dedup.py:3292-3410`, `tests/test_video_dedup.py:EndToEndVideoTests.test_mpeg_source_streams_as_fragmented_mp4_preview`).

## Quantified outcomes

- Counted 73 Python test methods in the repository at `fec73ed` (`git grep -n -E '^[[:space:]]*def test_' fec73ed -- tests | Measure-Object -Line`). This is a static count, not a coverage or pass-rate claim.
- Counted 8 frontend unit-test calls at `fec73ed` (`git grep -n -E '^[[:space:]]*(test|it)\(' fec73ed -- 'review-ui/src/lib/*.test.ts' | Measure-Object -Line`).
- Documented one local scan of 5,513 discovered and 4,715 scanned files, with 183,489 candidate pairs and 37,901.97 seconds elapsed; the report and cache remained local (`docs/performance-research.md:15-30`; commit `fec73ed`).
- Compared matching on 128 cached pairs over two runs per configuration: the documented median was 4.297 seconds serial and 3.986 seconds with two processes. Most sampled pairs were known matches, and the short batch ran alongside other workloads; it is not an end-to-end speedup measurement (`docs/performance-research.md:53-78`; commit `fec73ed`).

## Skills demonstrated

### Languages

- Name: Python
  - Context: Built the scanner and persisted local review data.
  - Evidence:
    - Orchestrated candidate generation and detailed matching in the scan pipeline — `video_dedup.py:_scan`.
    - Wrote review data through a temporary file and atomic replacement — `run_store.py:write_json` (commit `f5c8246`).
    - Preserved per-run success and failure records without overwriting the previous export on scan failure — `video_dedup.py:scan`, `tests/test_run_history.py:RunHistoryTests.test_scan_history_keeps_success_failure_and_previous_export` (commit `f5c8246`).

- Name: TypeScript
  - Context: Implemented typed review decisions and browser requests.
  - Evidence:
    - Synchronized keeper choices across reviewed sets sharing a file — `review-ui/src/lib/reviewDecisions.ts:updateDecisions` (commit `ddde4cd`).
    - Typed response payloads and surfaced failed requests to the interface — `review-ui/src/lib/api.ts:requestJson`.
    - Kept bulk selection limited to explicitly selected sets even when sets share videos — `review-ui/src/lib/groupSelection.ts:updateGroupSelection`, `review-ui/src/lib/groupSelection.test.ts:23-30` (commit `ddde4cd`).

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
    - Warned before closing a review with unsaved changes or a removal in progress — `review-ui/src/App.tsx:147-155`.

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
    - Reused unchanged exact file hashes without reading each file again — `tests/test_video_dedup.py:FingerprintTests.test_exact_hashes_are_reused_from_cache`.

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
    - Added a scanner test with an encoded re-encode and two-part compilation — `tests/test_video_dedup.py:EndToEndVideoTests.test_reencode_and_two_part_compilation`.

- Name: Playwright
  - Context: Wrote browser checks for review workflows and responsive layouts.
  - Evidence:
    - Added checks for review controls, accessible names, and desktop and mobile layouts — `review-ui/scripts/browser-smoke.cjs:main`.
    - Added checks for shared-file choices across review sets and after a page reload — `review-ui/scripts/shared-removal-smoke.cjs:checkRemoval`.

### Architecture

- Name: Perceptual hashing
  - Context: Compared video frames and regions to find visually similar footage.
  - Evidence:
    - Computed whole-frame and regional fingerprints for each sampled frame — `video_dedup.py:frame_sample`, `video_dedup.py:regional_frame_sample`.
    - Tested that moving obstructions survive candidate lookup and temporal matching — `tests/test_watermarks.py:RegionalFingerprintTests.test_moving_obstructions_survive_index_and_temporal_confirmation`.
    - Required enough informative matching tiles so a shared logo or flat background alone does not establish a regional match — `video_dedup.py:sample_distance`, `tests/test_watermarks.py:RegionalFingerprintTests.test_shared_logo_and_flat_background_tiles_are_not_enough`.

- Name: Graph algorithms
  - Context: Grouped matching video clips without conflating unrelated portions of the same compilation.
  - Evidence:
    - Used disjoint-set relationships for exact copies and overlapping match ranges to form clip-specific groups — `video_dedup.py:connected_components` (commit `a5eead7`).
    - Traversed exact-copy links when deciding whether retained videos fully cover a proposed removal — `video_dedup.py:covered_by`, `tests/test_video_dedup.py:FingerprintTests.test_exact_duplicate_coverage_is_transitive`.

- Name: Data integrity
  - Context: Guarded review data and media files against partial writes, invalid paths, and stale file metadata.
  - Evidence:
    - Flushed saved JSON before atomic replacement and tested that a failed replacement preserves the prior file — `run_store.py:write_json`, `tests/test_run_history.py:RunHistoryTests.test_failed_atomic_replace_preserves_existing_json` (commit `f5c8246`).
    - Rejected saved-plan identifiers that escape the run directory — `run_store.py:plan_path`, `tests/test_run_history.py:RunHistoryTests.test_invalid_names_ids_and_busy_load_leave_state_unchanged` (commit `f5c8246`).
    - Refused permanent deletion when a selected covering file changed after the scan — `video_dedup.py:WebReviewState._apply_reviewed`, `tests/test_web_operations.py:WebOperationTests.test_changed_keeper_is_refused_for_permanent_delete` (commit `f5c8246`).

- Name: Accessibility
  - Context: Added labeled review controls and keyboard and reduced-motion accommodations to the browser interface.
  - Evidence:
    - Named the duplicate-set navigation for assistive technologies — `review-ui/src/components/ReviewWorkspace.tsx:141-158` (commit `5f0fdd8`).
    - Labeled each video preview — `review-ui/src/components/FileCard.tsx:80-88` (commit `a2eb1b2`).
    - Added visible keyboard-focus styling — `review-ui/src/index.css:60-63` (commit `edef025`).
    - Reduced animation and transition durations when requested — `review-ui/src/index.css:94-102` (commit `a2eb1b2`).
    - Checked that buttons and checkboxes have accessible names in the browser smoke script — `review-ui/scripts/browser-smoke.cjs:main`.

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
    - Tested that progress stays readable while save, rescan, settings, and apply mutations are refused during quarantine — `tests/test_web_operations.py:WebOperationTests.test_progress_is_readable_during_quarantine_and_mutations_rejected` (commit `f5c8246`).

- Name: API design
  - Context: Connected the local review interface to session, plan, and file operations.
  - Evidence:
    - Routed review requests and returned errors for invalid bodies or missing request headers — `video_dedup.py:3492-3548`.
    - Defined client calls for loading and renaming plans and applying reviewed decisions — `review-ui/src/lib/api.ts:66-82`.
    - Served requested byte ranges for report-backed video previews — `video_dedup.py:3292-3342`, `tests/test_video_dedup.py:FingerprintTests.test_web_review_handler_serves_session_and_video_ranges`.

- Name: Performance profiling
  - Context: Investigated matching costs and compared local execution strategies without claiming a production speedup.
  - Evidence:
    - Compared serial, threaded, and process-based matching on cached pairs and recorded the batch size, repeated runs, and concurrent workload — `docs/performance-research.md:53-78` (commit `fec73ed`).
    - Recorded call-path timings and profiling overhead to identify candidate matching work for further investigation — `docs/performance-research.md:80-89` (commit `fec73ed`).

### Tooling

- Name: FFmpeg
  - Context: Extracted frames for matching and generated browser-compatible previews.
  - Evidence:
    - Sampled keyframes and scaled them for the fast fingerprint pass — `video_dedup.py:extract_fast`.
    - Streamed a transcoded preview for sources that need conversion — `video_dedup.py:3358-3410`.

- Name: Node.js
  - Context: Configured frontend unit tests and scripted local browser-test fixtures.
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

- Name: cProfile
  - Context: Documented a local profile of the detailed matching call path and its measurement overhead.
  - Evidence:
    - Recorded cumulative timings for matching and distance functions alongside the profiled and unprofiled runtimes — `docs/performance-research.md:80-89` (commit `fec73ed`).
