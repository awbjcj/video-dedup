# Video Dedup Review UI

React 18 + TypeScript frontend for the local `video-dedup web-review` server.
The browser loads duplicate sets from `/api/session`, streams browser-native
videos from `/api/video/:id`, and live-transcodes formats such as MPEG, AVI,
MKV, and legacy MPEG-4 to fragmented MP4 through `/api/preview/:id`. It also
requests coverage-safe recommendations and saves plans through `/api/plan`.
Reviewed portions of a plan can also be applied through `/api/apply-reviewed`;
the server moves selected files into quarantine and returns a refreshed review
session with completed sets removed. Each video card can also reveal its source
in the system file manager or open a native folder browser and move the source
while keeping the active session and report path in sync.

```powershell
pnpm install
pnpm build
pnpm bundle
pnpm lint
```

`pnpm bundle` writes the self-contained `bundle.html` served by
`video_dedup.py`. Start the Python server before running the browser smoke test:

```powershell
pnpm test:browser -- http://127.0.0.1:8765/ .\.tmp-browser-output
```

The frontend applies only reviewed, coverage-safe removals and always uses a
recoverable quarantine. Permanent deletion remains a separate CLI operation.
