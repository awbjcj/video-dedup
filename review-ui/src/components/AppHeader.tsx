import { HardDrive, Save, ShieldCheck, Undo2, Video } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { formatBytes, shortPath } from '@/lib/format'

type AppHeaderProps = {
  reportPath: string
  planPath: string
  groupCount: number
  fileCount: number
  decidedCount: number
  selectedRemovalCount: number
  estimatedReclaim: number
  dirty: boolean
  canUndo: boolean
  saving: boolean
  onUndo: () => void
  onSave: () => void
}
export function AppHeader({
  reportPath,
  planPath,
  groupCount,
  fileCount,
  decidedCount,
  selectedRemovalCount,
  estimatedReclaim,
  dirty,
  canUndo,
  saving,
  onUndo,
  onSave,
}: AppHeaderProps) {
  const progress = groupCount ? (decidedCount / groupCount) * 100 : 0

  return (
    <header className="border-b border-slate-800 bg-slate-950 text-white">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-4 px-4 py-4 lg:px-6">
        <div className="order-1 flex w-full shrink-0 items-center gap-3 sm:w-auto sm:min-w-[290px] sm:flex-1 sm:shrink">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-amber-400 text-slate-950 shadow-sm">
            <Video className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-semibold tracking-tight">Video Dedup Review</h1>
              {dirty ? (
                <Badge className="border-amber-300/30 bg-amber-300/10 text-amber-300 hover:bg-amber-300/10">Unsaved</Badge>
              ) : (
                <Badge className="border-emerald-300/30 bg-emerald-300/10 text-emerald-300 hover:bg-emerald-300/10">Saved</Badge>
              )}
            </div>
            <p className="mt-1 truncate font-mono text-xs text-slate-400" title={reportPath}>
              {shortPath(reportPath, 68)}
            </p>
          </div>
        </div>

        <div className="hidden h-9 w-px bg-slate-800 xl:block" />

        <dl className="order-3 grid w-full grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4 xl:order-none xl:flex xl:w-auto xl:flex-1 xl:flex-wrap xl:items-center">
          <div>
            <dt className="text-slate-400">Progress</dt>
            <dd className="mt-0.5 font-mono font-semibold text-slate-100">{decidedCount} / {groupCount} sets</dd>
          </div>
          <div>
            <dt className="text-slate-400">Files in review</dt>
            <dd className="mt-0.5 font-mono font-semibold text-slate-100">{fileCount.toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-slate-400">Selected removals</dt>
            <dd className="mt-0.5 font-mono font-semibold text-rose-300">{selectedRemovalCount.toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-slate-400">Potential space</dt>
            <dd className="mt-0.5 flex items-center gap-1 font-mono font-semibold text-amber-300">
              <HardDrive className="h-3.5 w-3.5" /> {formatBytes(estimatedReclaim)}
            </dd>
          </div>
        </dl>

        <div className="order-2 ml-auto flex w-full items-center justify-end gap-2 sm:w-auto">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={!canUndo || saving}
            onClick={onUndo}
            className="text-slate-300 hover:bg-slate-800 hover:text-white"
          >
            <Undo2 className="mr-2 h-4 w-4" /> Undo
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={saving}
            onClick={onSave}
            className="bg-amber-400 text-slate-950 hover:bg-amber-300"
            title={`Save to ${planPath}`}
          >
            {saving ? <ShieldCheck className="mr-2 h-4 w-4 animate-pulse" /> : <Save className="mr-2 h-4 w-4" />}
            {saving ? 'Saving…' : 'Save plan'}
          </Button>
        </div>
      </div>
      <Progress
        value={progress}
        aria-label="Review progress"
        aria-valuetext={`${decidedCount} of ${groupCount} sets reviewed`}
        className="h-1.5 rounded-none bg-slate-800 [&>div]:bg-amber-400"
      />
    </header>
  )
}
