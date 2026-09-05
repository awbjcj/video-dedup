# Contributing to Video Dedup

Thanks for considering a contribution. Video Dedup is built around a simple
safety boundary: scanning analyzes files, review records a decision, and only
apply can change the library. Preserve that boundary in every contribution.

## Before you start

- Search existing issues before opening a new one.
- For substantial changes, open an issue first so the problem and safety impact
  can be discussed before implementation.
- Never include personal videos, unredacted library paths, scan reports, plans,
  caches, or quarantine folders in an issue, commit, or pull request.
- Report a suspected vulnerability through the private process in
  [SECURITY.md](SECURITY.md), not through a public issue.

## Development setup

The CLI needs Python 3.10 or newer plus ffmpeg and ffprobe on PATH. It has no
third-party Python runtime dependencies.

~~~powershell
python .\video_dedup.py doctor
python -m unittest discover -s tests -v
~~~

The React review interface lives in review-ui. Install its locked development
dependencies only when working on that interface:

~~~powershell
pnpm -C review-ui install --frozen-lockfile
pnpm -C review-ui build
pnpm -C review-ui lint
~~~

## Required validation

Run the checks that cover the files you changed:

~~~powershell
python -m unittest discover -s tests -v
pnpm -C review-ui build
pnpm -C review-ui lint
git diff --check
~~~

If you modify review-ui source, also regenerate the checked-in bundle:

~~~powershell
pnpm -C review-ui bundle
~~~

Video Dedup serves review-ui/bundle.html directly. A UI source change without
its updated bundle is incomplete. For end-to-end UI work, run a web-review
server and then:

~~~powershell
pnpm -C review-ui test:browser -- http://127.0.0.1:8765/ .\.tmp-browser-output
~~~

## Tests and fixtures

Keep test media synthetic and small. The existing end-to-end tests create
temporary clips with FFmpeg; follow that pattern instead of committing real
footage. Add a regression test whenever a change affects duplicate matching,
plan persistence, path validation, or the scan/review/apply safety contract.

## Pull requests

Keep each pull request focused and explain:

1. the user-visible problem it solves;
2. any effect on scan output, plan compatibility, cache reuse, or deletion
   safety; and
3. the validation you ran.

Do not commit generated local artifacts such as the cache, reports, plans,
quarantine directories, node_modules, or screenshots. The exception is
review-ui/bundle.html, which is a deliberate checked-in release artifact.

Use a clear, imperative commit subject, for example: fix: preserve plan
decisions after a rescan. Maintainers may ask for a smaller follow-up when a
pull request mixes unrelated changes.

## Documentation

Update [README.md](README.md) when a user workflow changes and
[docs/architecture.md](docs/architecture.md) when a design boundary changes.
Documentation should describe observable behavior and trade-offs, not promise
unmeasured performance or compatibility.
