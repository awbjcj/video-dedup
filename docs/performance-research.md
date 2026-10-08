# Dedup performance research

Research date: October 5, 2026 (America/New_York). Code inspected: `ddde4cd`.
This is a research recommendation; the production scan code is unchanged.

## Recommendation

Optimize the Python matching stages and prototype a Rust matching extension before
considering a full rewrite. Extraction already uses concurrent FFmpeg subprocesses.
More Python threads do not address the serial CPU-heavy matching loops on the
installed CPython 3.11 build. A full Rust rewrite would still depend on video
decoding and disk throughput, while also requiring migration of unrelated review,
cache, reporting, and file-safety behavior.

## Evidence from this checkout

The latest completed local report contains 5,513 discovered files, 4,715 scanned
files, 183,489 candidate pairs, 145,508 pairs selected for detailed verification,
and 100,612 duplicate pairs. Elapsed time was 37,901.97 seconds (10 h 31 m 42 s).
It used 8 workers, a 6-second sample interval, a 12-second minimum segment, and
hash distance 50. These are observed settings, not recommended defaults.

About 79.3% of candidate pairs survived fast verification. This suggests the
prefilter is relatively permissive on this workload, but does not establish that
its matches are wrong or that a stricter threshold would preserve recall.

The report contains only total elapsed time. It cannot tell us how much of those
10.5 hours was decoding, matching, loading the cache, or handling failed files.
The `verified_pairs` counter is the size of the likely-pair list; individual
pairs can still be skipped when detailed extraction fails.

Current stage behavior:

| Stage | Implementation | Main opportunity |
|---|---|---|
| Fast extraction | `load_fast_records`, thread pool launching FFprobe/FFmpeg | Tune subprocess and decoder concurrency together |
| Exact hashing | `compute_exact_groups`, threaded SHA-256 for same-size files, cached | Storage throughput; low rewrite priority |
| Candidate generation | `build_candidates`, serial Python token index and ranking | Profile separately; reuse token representations |
| Fast verification | Serial loop over `fast_candidate_likely`; right-side token index cached | Batched CPU parallelism/native matching |
| Detailed extraction | `load_detailed_records`, thread pool launching FFmpeg | Decode/thread tuning, cache hits |
| Detailed verification | Serial loop over `detailed_match` and `matching_points` | Best measured native-code target |

`matching_points` rebuilds the right-hand token index on every pair. Unlike the
fast verifier, it has no reusable detailed token index. It repeatedly computes
region informativeness and regional distances, sorts those distances, and
allocates Python sets, lists, and tuples.

Short files are filtered after fast extraction, so a cold scan still extracts
their keyframes before discarding them. A metadata-first duration gate could
avoid that work, provided excluded files remain distinguishable from failures
and can be included on a later scan with a lower duration limit.

## Local experiment

Machine: Ryzen 9 5900HX, 8 physical cores / 16 logical processors; CPython 3.11.0.
Read-only access to existing cached fingerprints; no video decoding or cache
writes. Seed 42 selected 96 reported perceptual matches and 32 random pairs among
the selected video IDs. All 128 pairs had cache entries, representing 189 videos
with 2–1,026 detailed samples each (median 30). Report matching settings were used.

Each configuration ran twice. Process workers received the selected records once
through an initializer and then pair IDs in chunks of four. Times include pool
startup, serialization, work, and shutdown, but exclude initial report/cache loading.

| Configuration | Run 1 | Run 2 | Median |
|---|---:|---:|---:|
| Serial | 4.258 s | 4.337 s | 4.297 s |
| 4 Python threads | 4.390 s | 4.613 s | 4.502 s |
| 2 Python processes | 4.002 s | 3.969 s | 3.986 s |
| 4 Python processes | 4.008 s | 4.404 s | 4.206 s |
| 8 Python processes | 6.205 s | 5.672 s | 5.939 s |

All returned results matched the serial baseline exactly. These are short-batch
measurements, not sustained throughput or end-to-end speedups. An existing dedup
scan and review server were running concurrently; neither was stopped. The sample
overrepresents known positives, does not reconstruct the full candidate workload,
and is too small to select a production worker count. In particular, the process
results do not rule out substantial gains from a persistent pool on a long run.

A separate cProfile pass took 16.55 seconds, versus about 4.30 seconds without
profiling. Its cumulative times identify call paths, not additive stage timings:

- `matching_points`: 16.21 seconds, approximately 98% of profiled execution.
- `sample_distance`: 13.68 seconds across 589,540 calls.
- `whole_sample_distance`: 6.49 seconds across 5.83 million calls.
- `int.bit_count`: only 0.70 seconds across 11.66 million calls.

This favors moving the comparison loop and its data structures together; merely
replacing Python's already-native integer popcount is unlikely to be sufficient.

Local reproduction artifacts, intentionally ignored by Git:
`.tmp-performance/benchmark.py` and `.tmp-performance/results.json`.
Run `python .tmp-performance/benchmark.py` from the repository root. It requires
the current local report and matching cache, so later library changes can change
its selected workload and results.

## Ranked next steps

### 1. Measure full stages and remove repeat work

Record wall time for cache load, probing/fast extraction, exact hashing,
candidate generation, fast verification, detailed extraction, detailed
verification, and report writing. Include cache hit counts, pair/sample counts,
peak memory, and extraction failures. Separate cold scans from warm rescans.

Precompute informative-region masks and tokens. Add a bounded detailed token-index
cache, preferably grouping tasks by the right-hand video to encourage reuse.
Measure memory: retaining every Python token index for the entire library could
cost substantially more than the compressed SQLite data.

Cache pair-verification results, including negative results. Keys must include
both fingerprint identities, matching-algorithm version, hash distance, interval,
and minimum segment. Persist raw match results before the report percentage
filter so changing that filter need not rerun matching. Never treat decode failure
as a negative match. This can make repeated scans cheaper regardless of language.

### 2. Compare persistent process workers with a Rust extension

A process-pool prototype is the lower-dependency implementation experiment.
Use separate matching-worker and decode-worker settings; batch pair IDs, bound
queued work, keep SQLite writes in the coordinator, and avoid sending the full
library or duplicate Python object graphs with every task. Windows process
startup and memory replication must be included in measurements. A packed
read-only memory-mapped fingerprint store is a possible later improvement if
serialization or per-process memory dominates.

For Rust, use a narrow PyO3 boundary around a batch matcher. Convert packed
fingerprints once into Rust-owned storage, release the interpreter lock with
`Python::detach`, and parallelize independent pairs with Rayon. Bound the native
worker count. Avoid calling Python once per frame comparison.

Start with `matching_points` and regional distance calculation; expand to the
whole `detailed_match` batch if returning intermediate points becomes expensive.
Then consider `fast_candidate_likely`, token generation, and candidate ranking if
stage profiles justify them. Keep a Python fallback. Preserve FFmpeg, SQLite,
report schemas, review UI, and apply behavior.

Rust needs exact semantic parity: Python's rounding/tie behavior, offset ranking,
one-to-one temporal alignment, flat-region handling, the seven-of-nine regional
rule, confidence, and coverage normalization all affect results. Preserve
64-bit hash operations and wrapping behavior in token ranking. Do not replace
the detailed distance with a boolean threshold check: downstream alignment and
confidence use the actual distance. A whole-frame threshold short-circuit is
potentially safe for the fast verifier's boolean decision, but requires parity
tests and a separate predicate.

Rust brings wheel/build maintenance and an additional implementation to test.
No Rust implementation was benchmarked here, so no Rust speedup is claimed.

### 3. Tune FFmpeg for cold scans

The current extraction commands set neither decoder threads nor filter threads.
FFmpeg can create internal thread pools in addition to the outer worker pool.
Benchmark a small representative codec/resolution set across 1/2/4/8 extraction
workers and explicit decoder/filter thread limits. Measure disk throughput and
CPU usage; select different settings for HDD and SSD workloads if needed.

The fast pass already uses keyframe-only decoding. The detailed pass uses an
`fps` filter after decoding; reducing retained samples does not imply a matching
reduction in compressed-video decoding. Keyframe-only detailed verification
would change detection behavior and should not be treated as a transparent
optimization. Hardware decoding is a separate experiment, with pixel/fingerprint
parity checks and transfer overhead included.

Expose new performance controls in the review settings and preserve them in
rescan/report settings, so browser users can tune them too.

## Acceptance and decision gates

1. Establish quiet-machine cold, warm, and matching-only baselines, using multiple
   runs and workloads spanning short/long videos, negative pairs, watermarks,
   compilations, and high-frequency visual tokens.
2. Compare current Python, Python with reusable indexes, persistent processes,
   single-thread Rust, and parallel Rust on identical candidates and fingerprints.
3. Compare complete normalized match output, including directional ranges,
   confidence and exact/perceptual classification. Run the existing Python suite
   and add differential tests for any optimized matching implementation.
4. Track peak memory and cancellation/resume behavior alongside elapsed time.
   Preserve the single-writer cache boundary and deterministic output ordering.
5. Choose the smallest implementation with a meaningful measured end-to-end
   gain. A full rewrite is justified only by additional requirements that a
   native extension cannot meet; this investigation supplies no such evidence.

For illustration only, accelerating a stage that consumes 70% of runtime by 5x
would yield approximately 2.27x overall speedup, not 5x. The actual stage fraction
is currently unknown.

## Documentation consulted

Current documentation was resolved and queried through Context7, then checked
against primary sources:

- [Python concurrent.futures](https://docs.python.org/3/library/concurrent.futures.html):
  process pools bypass the GIL, require serializable data, and benefit from batching.
  Python 3.14 interpreter pools are another option, but are unavailable in the
  installed 3.11 runtime and still serialize work across interpreter boundaries.
- [PyO3 parallelism](https://pyo3.rs/main/parallelism): detaching from Python and
  using Rust parallel work. Pin the chosen release before implementation because
  the linked guide follows the current development branch.
- [FFmpeg options](https://ffmpeg.org/ffmpeg-all.html): decoder threading and
  `-filter_threads`; filter pools default to the available CPU count.
