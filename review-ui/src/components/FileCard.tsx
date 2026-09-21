import { useRef, useState } from 'react'
import { Check, Copy, FileInput, FileWarning, FolderSearch, LoaderCircle, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { DuplicateTimeline } from '@/components/DuplicateTimeline'
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
  onOpenInFolder: () => Promise<void>
  onMoveToFolder: () => Promise<void>
}

export function FileCard({
  file,
  kept,
  canRemove,
  onToggle,
  onKeepOnly,
  onCopied,
  onOpenInFolder,
  onMoveToFolder,
}: FileCardProps) {
  const [videoFailed, setVideoFailed] = useState(false)
  const [fileAction, setFileAction] = useState<'open' | 'move' | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)

  async function copyPath() {
    await navigator.clipboard.writeText(file.path)
    onCopied()
  }

  async function runFileAction(action: 'open' | 'move') {
    setFileAction(action)
    try {
      await (action === 'open' ? onOpenInFolder() : onMoveToFolder())
    } finally {
      setFileAction(null)
    }
  }

  return (
    <article
      className={cn(
        'group overflow-hidden rounded-xl border bg-white surface-shadow transition-[border-color,box-shadow,background-color] duration-200',
        kept
          ? 'border-slate-200 hover:border-slate-300 hover:surface-shadow-strong'
          : 'border-rose-300 bg-rose-50/40 ring-1 ring-rose-200 hover:border-rose-400',
      )}
    >
      <div className="relative aspect-video bg-slate-950">
        {videoFailed ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-6 text-center text-base text-slate-300">
            <FileWarning className="h-7 w-7 text-amber-400" aria-hidden="true" />
            <span>
              {file.previewMode === 'transcoded'
                ? 'Live compatibility preview failed. Confirm FFmpeg can decode this file.'
                : 'Preview unavailable. The source file may have moved or the browser may not support its codec.'}
            </span>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="mt-1"
              onClick={() => setVideoFailed(false)}
            >
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" /> Retry preview
            </Button>
          </div>
        ) : (
          <video
            ref={videoRef}
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
            'pointer-events-none absolute left-2 top-2 rounded-md px-2.5 py-1.5 text-xs font-bold uppercase tracking-wide shadow-md',
            kept ? 'bg-emerald-500 text-emerald-950' : 'bg-rose-600 text-white',
          )}
        >
          {kept ? 'Keep' : 'Quarantine'}
        </div>
        {file.previewMode === 'transcoded' ? (
          <div className="pointer-events-none absolute right-2 top-2 rounded-md bg-slate-800/90 px-2.5 py-1.5 text-xs font-semibold uppercase tracking-wide text-slate-100 shadow-sm backdrop-blur-sm">
            Live transcode
          </div>
        ) : null}
      </div>
      <DuplicateTimeline
        fileName={file.name}
        duration={file.durationSeconds}
        ranges={file.duplicateRanges}
        onSeek={(seconds) => {
          if (!videoRef.current) return
          videoRef.current.currentTime = seconds
          videoRef.current.focus()
        }}
      />

      <div className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold leading-snug text-slate-950" title={file.name}>
              {file.name}
            </h3>
            <p className="mt-1 truncate font-mono text-xs leading-relaxed text-slate-600" title={file.path}>
              {shortPath(file.folder)}
            </p>
          </div>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="shrink-0 text-slate-600"
            onClick={() => void copyPath()}
            aria-label={`Copy path for ${file.name}`}
          >
            <Copy className="h-4 w-4" aria-hidden="true" />
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

        <div className="mt-3 grid grid-cols-2 gap-2" aria-label={`File actions for ${file.name}`}>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={fileAction !== null}
            onClick={() => void runFileAction('open')}
          >
            {fileAction === 'open' ? (
              <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <FolderSearch className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
            )}
            Open in folder
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={fileAction !== null}
            onClick={() => void runFileAction('move')}
          >
            {fileAction === 'move' ? (
              <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <FileInput className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
            )}
            {fileAction === 'move' ? 'Choose folder…' : 'Move…'}
          </Button>
        </div>

        <div className="mt-4 border-t border-slate-200 pt-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-600">Covered by this set</span>
            <span className="font-mono font-semibold text-slate-800">{file.coveredPercent.toFixed(1)}%</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200" aria-hidden="true">
            <div
              className={cn('h-full rounded-full', file.coveredPercent >= 95 ? 'bg-emerald-500' : 'bg-amber-500')}
              style={{ width: `${Math.min(100, Math.max(0, file.coveredPercent))}%` }}
            />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
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
              <span className="flex items-center gap-1.5"><Check className="h-4 w-4 text-emerald-600" aria-hidden="true" /> Keep file</span>
            ) : (
              <span className="flex items-center gap-1.5 text-rose-700"><Trash2 className="h-4 w-4" aria-hidden="true" /> Quarantine</span>
            )}
          </label>
          <Button type="button" size="sm" variant="ghost" onClick={onKeepOnly}>
            <ShieldCheck className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" /> Keep only this
          </Button>
        </div>
      </div>
    </article>
  )
}
