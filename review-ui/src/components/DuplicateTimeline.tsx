import { Copy } from 'lucide-react'

import { formatDuration } from '@/lib/format'
import type { DuplicateRange } from '@/types'

type DuplicateTimelineProps = {
  fileName: string
  duration: number
  ranges: DuplicateRange[]
  onSeek: (seconds: number) => void
}

export function DuplicateTimeline({
  fileName,
  duration,
  ranges,
  onSeek,
}: DuplicateTimelineProps) {
  const duplicatedSeconds = ranges.reduce(
    (total, range) => total + Math.max(0, range.endSeconds - range.startSeconds),
    0,
  )

  return (
    <div className="border-t border-slate-700 bg-slate-900 px-3 py-3 text-slate-100">
      <div className="mb-2 flex items-center justify-between gap-3 text-xs">
        <span className="flex items-center gap-1.5 font-semibold">
          <Copy className="h-3.5 w-3.5 text-amber-400" aria-hidden="true" />
          Duplicated footage
        </span>
        <span className="font-mono text-slate-300">
          {formatDuration(duplicatedSeconds)} of {formatDuration(duration)}
        </span>
      </div>
      <div
        className="relative h-4 overflow-hidden rounded-sm border border-slate-600 bg-slate-700"
        aria-label={`Duplicate timeline for ${fileName}`}
      >
        {ranges.map((range, index) => {
          const left = duration > 0 ? (range.startSeconds / duration) * 100 : 0
          const width = duration > 0
            ? ((range.endSeconds - range.startSeconds) / duration) * 100
            : 0
          const label = `Duplicate segment ${formatDuration(range.startSeconds)} to ${formatDuration(range.endSeconds)}. Seek to segment.`
          return (
            <button
              key={`${range.startSeconds}-${range.endSeconds}-${index}`}
              type="button"
              className="duplicate-timeline-segment absolute inset-y-0 min-w-1 border-x border-amber-200/70 focus-visible:z-10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-white"
              style={{ left: `${left}%`, width: `${width}%` }}
              onClick={() => onSeek(range.startSeconds)}
              aria-label={label}
              title={label}
            />
          )
        })}
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
        Striped marks show matched sections. Select a mark to jump there.
      </p>
    </div>
  )
}
