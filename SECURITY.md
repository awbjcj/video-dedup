# Security Policy

## Supported versions

Video Dedup does not currently maintain parallel release branches. Security
fixes are made on the latest master branch, currently the 1.5.x line.

| Version | Supported |
| --- | --- |
| Current master / 1.5.x | Yes |
| Earlier versions | No |

## Reporting a vulnerability

Please do not open a public GitHub issue for a suspected vulnerability. Use the
[private security advisory form](https://github.com/awbjcj/video-dedup/security/advisories/new)
instead.

Include enough detail to reproduce and assess the issue:

- the affected command or local review endpoint;
- the Video Dedup version, operating system, Python version, and FFmpeg version;
- a minimized, sanitized reproduction; and
- the observed and expected behavior.

Do **not** upload private videos, full scan reports, plans, caches, or paths
from a personal media library. Explain how to create synthetic test inputs
instead.

## Scope

Reports are particularly useful for issues involving:

- path traversal or unintended file access;
- accidental mutation outside an explicit apply action;
- bypasses of the size and modification-time checks before applying a plan;
- local review server request handling, preview transcoding, or exposure caused
  by binding the server beyond loopback; and
- malformed report or plan data that can cause unsafe behavior.

The web review server binds to 127.0.0.1 by default. Treat an explicit host
choice of 0.0.0.0 or :: as a network-exposure decision and do not use it on an
untrusted network without appropriate controls.

## Disclosure

Please allow time for a fix or mitigation before public disclosure. The
maintainer will use the private advisory to coordinate status and a disclosure
timeline.
