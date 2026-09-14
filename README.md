# Video Dedup

`video_dedup.py` finds byte-identical videos, re-encoded copies, clips embedded
inside longer videos, and compilations made from several other videos. It is
designed for libraries around 10,000 files where videos are under 30 minutes.

The tool never removes a file during scanning. A separate interactive review
creates a JSON plan, and applying that plan moves files to a quarantine folder
by default.

## Install and verify

Video Dedup uses only the Python standard library. FFmpeg and FFprobe provide
video probing and frame extraction; Node.js is needed only when changing the
review UI. The examples below use PowerShell, but the Python commands work on
other platforms after adjusting path syntax.

### Requirements

- Python 3.10+
- `ffmpeg` and `ffprobe` on `PATH`

### Install from source

```powershell
git clone https://github.com/awbjcj/video-dedup.git
cd video-dedup
```

### Check the setup

```powershell
python .\video_dedup.py doctor
```

## Open source community

- [Architecture](docs/architecture.md) explains the scan, review, and apply
  boundaries and the local browser server.
- [Contributing guide](CONTRIBUTING.md) covers setup, validation, and the
  checked-in UI bundle.
- [Security policy](SECURITY.md) explains how to report vulnerabilities
  privately.
- [Support guide](SUPPORT.md) routes questions, bugs, and feature requests.
- [Code of Conduct](CODE_OF_CONDUCT.md) sets expectations for collaboration.

Reports and plans can contain absolute paths, filenames, durations, and other
details about a personal media library. Do not attach private videos, raw scan
reports, or plans to a public issue; use a minimized, sanitized reproduction.

Video Dedup is released under the [MIT License](LICENSE).

## Typical workflow

For one-command startup with the default `video-dedup-report.json` and
`video-dedup-plan.json` paths:

```powershell
make start
```

Override any startup path or port when needed:

```powershell
make start REPORT=duplicates.json PLAN=decisions.json PORT=0
```

Scan two roots, including three subfolder levels:

```powershell
python .\video_dedup.py scan "D:\Videos" "E:\Phone videos" --depth 3 --report .\duplicates.json
```

`--depth 0` scans only the named folders. `--depth -1` is unlimited. The first
run can take substantial time; `.video-dedup-cache.sqlite3` makes later scans
incremental. Lower `--workers` when scanning a slow hard disk; raise it carefully
on an SSD.

Review duplicate sets visually in the local browser (recommended):

```powershell
python .\video_dedup.py web-review .\duplicates.json --plan .\decisions.json
```

The browser opens automatically and provides video previews, duplicate-range
timelines, search and sorting, keeper checkboxes, bulk set selection, reusable
recommendations, undo, review progress, and a save summary. Select a striped
timeline segment to jump to the matching footage. Large sets are paged so only
twelve video players are loaded at once. If the named plan already exists, its
decisions are resumed.

Use **Settings** in the review header to configure the minimum duplicated
timeline, minimum video duration, deletion safety coverage, watermark/re-encode
tolerance, frame sample interval, and minimum matching segment. Review filters
apply immediately. Accuracy changes can start a safe rescan from the same dialog;
the existing fingerprint cache is reused and no video file is modified.

The server listens only on `127.0.0.1` by default. It can read only video IDs
listed in the report. **Save plan** writes decisions without changing videos.
**Apply reviewed** moves coverage-safe removals from reviewed sets into a
timestamped quarantine beside the plan. Successfully applied sets are removed
from the active plan and review queue; refused sets remain available to retry.
Permanent deletion remains CLI-only. Press `Ctrl+C` in the terminal to stop it.
If port 8765 is occupied, let the operating system choose a free port:

```powershell
python .\video_dedup.py web-review .\duplicates.json --plan .\decisions.json --port 0
```

For terminal-only use, review one set at a time:

```powershell
python .\video_dedup.py review .\duplicates.json --plan .\decisions.json
```

Or open the batch review shell:

```powershell
python .\video_dedup.py review .\duplicates.json --batch --plan .\decisions.json
```

Batch commands accept individual set numbers, comma-separated values, and
ranges. A typical session can apply a safe starting strategy to hundreds of
sets and then override exceptions:

```text
batch> strategy 1-300 delete-shallower
batch> list 301-320
batch> show 307
batch> keep 307 1,3
batch> skip 308-315
batch> undo
batch> status
batch> done
```

`keep SETS FILES` uses the displayed file numbers within each selected set, so
`keep 1-100 1` keeps the first listed file in each of those sets. `skip` keeps
every file. `unset` clears earlier decisions, and `undo` reverses the most recent
batch edit. Saving with unresolved sets requires confirmation and safely keeps
all files in those sets. `save` is an alias for `done`.

Plans now retain the full keeper decisions as well as the removal actions. Reopen
a plan to change any earlier decisions; unless `--plan` names a new output, the
edited plan is written back to the same path:

```powershell
python .\video_dedup.py review .\duplicates.json --edit-plan .\decisions.json
```

Or generate a non-interactive plan with an optional removal strategy:

```powershell
python .\video_dedup.py review .\duplicates.json --plan .\decisions.json --strategy delete-shallower
```

Available strategies are:

- `manual`: prompt for keepers in every set (default).
- `delete-shallower`: remove files in shallower folders first; depth is measured
  relative to the scanned roots.
- `delete-shorter-name`: remove shorter filenames first.
- `delete-numbered-name`: remove filenames containing both letters and digits
  first, such as `clip2.mp4`.
- `delete-fully-covered`: remove the most completely covered files first, while
  recalculating coverage after each choice.

Automatic strategies only add an action when the remaining keepers cover at
least `--minimum-delete-coverage` percent of that file (95% by default). They
never plan removal of the final file in a duplicate set. Ties prefer removing
the lower-resolution, smaller file. The resulting JSON is still only a plan;
`apply` remains a separate step.

Apply the reviewed plan. This moves selected files into a new timestamped
quarantine directory and records every move:

```powershell
python .\video_dedup.py apply .\decisions.json
```

Permanent deletion is deliberately explicit:

```powershell
python .\video_dedup.py apply .\decisions.json --permanent
```

## Understanding percentages

Coverage is directional. If `clip-a.mp4` is one half of `compilation.mp4`, the
report can show:

- `clip-a.mp4`: 100% duplicated by the compilation
- `compilation.mp4`: 50% duplicated by `clip-a.mp4`

During review, coverage from multiple selected keepers is combined. Keeping
both source clips can therefore cover 100% of a compilation, while keeping the
compilation can cover 100% of each source clip.

The report includes `confidence`, matched sample ranges, failures, and the scan
settings. Perceptual matching examines video frames, not audio tracks. Review
videos with alternate audio, commentary, or dubbing before removing them.

## Accuracy and scale controls

- `--min-duration 10`: ignore video files shorter than ten seconds during scans
  and review. Set it to `0` to include every duration.
- `--sample-interval 3`: confirmation frame spacing; smaller is more accurate
  but slower and creates larger reports.
- `--min-segment 9`: shortest overlap to report.
- `--min-duplicate-percent 95`: only report a pair when either video's matched
  timeline reaches the requested percentage. The default `0` preserves all
  sufficiently long matches.
- `--hash-distance 20`: visual tolerance; lower reduces false positives.
- `--candidate-tokens 512`: memory/recall tradeoff for the 10k-file index.
- `--max-candidates-per-video 50`: bounds worst-case confirmation work.
- `--workers 4`: simultaneous FFmpeg processes.

The scanner first indexes perceptual hashes of key frames, ignores overly common
visual tokens and flat frames, and only fully decodes likely candidates. The fast
pass probes metadata once and emits at most `--max-fast-frames` time-spaced key
frames, avoiding a second key-frame decode. Results are probabilistic: heavy
cropping, overlays, speed changes, mirrored video, or a library dominated by
nearly identical static footage may require tuning and manual review.

Successful fast/detailed fingerprints and exact SHA-256 hashes are cached by
path, size, and nanosecond modification time. Decode failures are cached too, so
unchanged corrupt files do not slow every later scan. Changed files retry
automatically; use `--retry-failures` after changing the FFmpeg installation or
when a transient failure has cleared. Cache writes are committed in small
batches; an interruption can lose only the current batch, and completed prior
batches remain reusable.

## JSON policy and safety

`doctor`, `scan`, and `apply` print a stable JSON result to stdout; progress goes
to stderr. The full scan report and decision plan use `schema_version: 1`.

Before applying a plan, the tool verifies each file's byte size and nanosecond
modification time. Changed files are refused. Quarantined filenames receive a
numeric prefix to avoid collisions, and an adjacent `.result.json` records the
outcome.

## Frontend development

The checked-in `review-ui/bundle.html` is self-contained, so users do not need
Node.js. To change the React 18 + TypeScript source or rebuild the bundle:

```powershell
cd .\review-ui
pnpm install
pnpm build
pnpm bundle
pnpm lint
```

Run `pnpm test:browser -- http://127.0.0.1:8765/ .\.tmp-browser-output` while a
`web-review` server is running to exercise the rendered bulk-review workflow.
