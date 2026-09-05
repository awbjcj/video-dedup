# Support

## Start with the documentation

- [README.md](README.md) covers installation, the scan-review-apply workflow,
  safety controls, and tuning.
- [docs/architecture.md](docs/architecture.md) explains the design boundaries.
- Run python .\video_dedup.py doctor to verify Python, FFmpeg, and FFprobe.
- Run python .\video_dedup.py --help to list the supported commands and options.

## Where to ask

Use GitHub Issues for reproducible bugs and well-scoped feature requests. The
issue forms ask for the details needed to investigate without exposing a media
library.

Before reporting a problem, include:

- the output of python .\video_dedup.py --version;
- your operating system and FFmpeg version;
- the exact command with personal paths replaced;
- the observed result and the expected result; and
- a synthetic or otherwise sanitized reproduction when possible.

For a security concern, follow [SECURITY.md](SECURITY.md) and use the private
advisory form rather than a public issue.

## Privacy

Do not post video files, raw reports, review plans, caches, quarantine folders,
or identifying paths in public. Those files often reveal names, locations, and
other private details about a media library.

Support is provided on a best-effort basis. Clear, small reproductions make it
much easier to help.
