import { useState } from 'react'
import { Check, Copy, FileWarning, ShieldCheck, Trash2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { formatBytes, formatDuration, shortPath } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { VideoFile } from '@/types'

type FileCardProps = {
  file: VideoFile
  kept: boolean
  canRemove: boolean
  onToggle: () => void
  onKeepOnly: () => void
  onCopied: () => void
}

export function FileCard({
  file,
  kept,
  canRemove,
  onToggle,
  onKeepOnly,
  onCopied,
}: FileCardProps) {
  const [videoFailed, setVideoFailed] = useState(false)

  async function copyPath() {
    await navigator.clipboard.writeText(file.path)
    onCopied()
  }

  return (
    <article
      className={cn(
        'overflow-hidden rounded-md border bg-white transition-colors',
        kept ? 'border-slate-200' : 'border-rose-300 bg-rose-50/50',
      )}
    >
      <div className="relative aspect-video bg-slate-950">
        {videoFailed ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-6 text-center text-sm text-slate-400">
            <FileWarning className="h-7 w-7 text-amber-400" />
            Preview unavailable. The source file may have moved or the browser may not support its codec.
          </div>
        ) : (
          <video
            className="h-full w-full object-contain"
            controls
            playsInline
            preload="metadata"
            src={file.videoUrl}
            onError={() => setVideoFailed(true)}
            aria-label={`Preview ${file.name}`}
          />
        )}
        <div
          className={cn(
            'pointer-events-none absolute left-2 top-2 rounded-sm px-2 py-1 text-[11px] font-bold uppercase tracking-wide shadow-sm',
            kept ? 'bg-emerald-500 text-emerald-950' : 'bg-rose-600 text-white',
          )}
        >
          {kept ? 'Keep' : 'Quarantine'}
        </div>
      </div>

      <div className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-slate-950" title={file.name}>
              {file.name}
            </h3>
            <p className="mt-1 truncate font-mono text-[11px] text-slate-500" title={file.path}>
              {shortPath(file.folder)}
            </p>
          </div>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="h-8 w-8 shrink-0 text-slate-500"
            onClick={() => void copyPath()}
            aria-label={`Copy path for ${file.name}`}
          >
            <Copy className="h-4 w-4" />
          </Button>
        </div>

        <div className="mt-3 flex flex-wrap gap-1.5">
          <Badge variant="secondary" className="font-mono font-normal">
            {formatDuration(file.durationSeconds)}
          </Badge>
          <Badge variant="secondary" className="font-mono font-normal">
            {file.width}×{file.height}
          </Badge>
          <Badge variant="secondary" className="font-mono font-normal">
            {formatBytes(file.sizeBytes)}
          </Badge>
          <Badge variant="outline" className="font-mono font-normal text-slate-500">
            {file.codec}
          </Badge>
        </div>

        <div className="mt-3 flex items-center justify-between gap-3 border-t border-slate-100 pt-3 text-xs">
          <span className="text-slate-500">Covered by this set</span>
          <span className="font-mono font-semibold text-slate-800">{file.coveredPercent.toFixed(1)}%</span>
        </div>

        <div className="mt-4 flex items-center justify-between gap-2">
          <label
            htmlFor={`keep-file-${file.id}`}
            className="flex cursor-pointer items-center gap-2 text-sm font-medium text-slate-800"
          >
            <Checkbox
              id={`keep-file-${file.id}`}
              checked={kept}
              disabled={kept && !canRemove}
              onCheckedChange={onToggle}
              className="data-[state=checked]:border-emerald-600 data-[state=checked]:bg-emerald-600"
            />
            {kept ? (
              <span className="flex items-center gap-1.5"><Check className="h-4 w-4 text-emerald-600" /> Keep file</span>
            ) : (
              <span className="flex items-center gap-1.5 text-rose-700"><Trash2 className="h-4 w-4" /> Quarantine</span>
            )}
          </label>
          <Button type="button" size="sm" variant="ghost" className="h-8 text-xs" onClick={onKeepOnly}>
            <ShieldCheck className="mr-1.5 h-3.5 w-3.5" /> Keep only this
          </Button>
        </div>
      </div>
    </article>
  )
}
