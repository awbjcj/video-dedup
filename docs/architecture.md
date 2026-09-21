# Architecture

Video Dedup is a local, review-first tool. Its central design decision is to
separate finding possible duplicates from deciding what to keep and from
changing files on disk.

~~~text
folders or files
      |
      v
    scan --------------> report.json
      |                       |
      |                       v
fingerprint cache       review / web-review
                              |
                              v
                          plan.json
                              |
                              v
                            apply
                              |
                              v
                       quarantine (default)
~~~

## Scan: read-only analysis

Scan discovers supported video files, probes them with FFprobe, and records
failures without modifying the media library. It uses three matching stages:

1. Files with the same size are checked with SHA-256 to identify byte-exact
   duplicates.
2. Inexpensive key-frame fingerprints create a bounded candidate index rather
   than comparing every pair in a large library.
3. Only likely candidates are decoded at a fixed interval for perceptual
   confirmation and matched timeline ranges.

Both extraction passes downscale grayscale frames to 27 by 24 pixels. Each
sample stores a whole-frame dHash/aHash and nine independent 9-by-8 regional
hashes. Region-position tokens participate in candidate retrieval as well as
confirmation, so a watermark affecting the global hash does not eliminate the
pair before regional comparison. Whole-frame tokens retain reserved space in
the bounded per-video token budget.

Frame distance is the smaller of the whole-frame distance and a regional
distance. The regional path requires at least seven informative corresponding
tiles, trims the two worst regions, and uses the larger of the retained mean
distance and the fifth-best distance, plus a four-point penalty. This requires
a majority of the picture to agree while tolerating watermark boundaries across
tiles. The excluded regions are selected per frame, allowing floating logos.
Flat tiles cannot supply evidence. The existing hash-distance setting controls
both paths, and zero remains strict. Confirmation favors the established time
offset over a slightly better-looking neighboring frame to prevent overlays
from creating artificial gaps in timeline coverage.

The report records the scan settings, files, matches, failures, and a summary.
The tool writes JSON to the requested report path and emits a stable JSON result
on stdout; progress belongs on stderr.

### Incremental cache

The SQLite cache stores exact hashes and fast/detailed fingerprints keyed by
path, byte size, nanosecond modification time, fingerprint kind, and sampling
interval. It also remembers decode failures. A file changed on disk gets new
work automatically; retry-failures retries unchanged failures after an
environment problem is fixed.

Version 1.6 uses new fast/detailed cache kinds for regional fingerprints. Earlier
visual rows are not reused, and the first rescan extracts the additional data.
Exact SHA-256 cache entries remain compatible. Regional samples cost more memory
and storage than the old whole-frame samples; candidate token and pair caps still
apply.

The cache improves repeated scans, but it is not a source of truth and is
ignored by Git. Deleting it is safe; the next scan simply rebuilds it.

## Review: decisions without mutation

Both review commands turn report matches into connected duplicate sets. They
calculate directional coverage: a short clip can be fully covered by a longer
compilation even when the longer compilation is only partly covered by the
clip.

Review produces a JSON plan containing keeper decisions and proposed actions.
Automatic strategies require the remaining keepers to meet the configured
minimum deletion coverage and never plan removal of the final file in a set.
Saving a plan does not move or delete files.

## Apply: explicit, validated mutation

Apply is the only command that changes media files. Before it acts on every
planned file, it compares the current byte size and nanosecond modification time
against the plan. A mismatch is refused.

The default action is to move files into a newly created, timestamped quarantine
directory beside the plan. The result is recorded in an adjacent result JSON
file. Permanent deletion requires a permanent flag and an explicit DELETE
confirmation unless the yes flag is supplied for automation.

This is a safety mechanism, not a backup strategy. Keep independent backups of
media that cannot be replaced.

## Local browser review

Web review starts a Python ThreadingHTTPServer on 127.0.0.1 by default. It
serves a self-contained browser bundle plus only the report-backed review data
and media routes needed by the current session. The server saves plans and can
apply the reviewed portion of a plan to a recoverable quarantine. It repeats
the size and modification-time checks, records a result, removes successfully
completed sets from the active plan, and leaves refused sets available to retry.
Permanent deletion remains CLI-only.

Some containers or codecs are not browser-native. For those, the local server
uses FFmpeg to stream a fragmented MP4 preview as it is requested. This makes
review more broadly compatible without rewriting the source video.

The server is intentionally local and unauthenticated. Binding it to 0.0.0.0
or :: makes it reachable beyond the local machine and should be treated as a
deliberate exposure decision.

## UI delivery

The editable React 18 and TypeScript UI lives in review-ui/src. The Python
server does not run a Node development server: it reads the checked-in,
self-contained review-ui/bundle.html. Therefore:

- users need Python, FFmpeg, and FFprobe, not Node.js, to use Video Dedup;
- UI contributors build, lint, and bundle the frontend with pnpm; and
- every frontend source change must include the regenerated bundle.

The browser smoke test exercises the bundled UI against a running local
web-review instance, including responsive and accessibility checks.

## Compatibility and limits

Perceptual matching examines video frames, not audio. Static and floating
watermarks are tolerated through regional comparisons, but large/full-screen
overlays and low-detail footage can still defeat matching. Cropping, speed
changes, mirroring, unusual codecs, or many nearly identical static scenes can
affect results. Tune scan settings when appropriate and manually review every
proposed removal. A report is an aid to review, not proof that a file is safe to
delete.
