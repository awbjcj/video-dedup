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
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 lg:px-6">
        <div className="flex min-w-[260px] items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-amber-400 text-slate-950">
            <Video className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-base font-semibold tracking-tight">Video Dedup Review</h1>
              {dirty ? (
                <Badge className="border-amber-300/30 bg-amber-300/10 text-amber-300 hover:bg-amber-300/10">Unsaved</Badge>
              ) : (
                <Badge className="border-emerald-300/30 bg-emerald-300/10 text-emerald-300 hover:bg-emerald-300/10">Saved</Badge>
              )}
            </div>
            <p className="mt-0.5 truncate font-mono text-[11px] text-slate-500" title={reportPath}>
              {shortPath(reportPath, 68)}
            </p>
          </div>
        </div>

        <div className="hidden h-9 w-px bg-slate-800 xl:block" />

        <dl className="flex flex-1 flex-wrap items-center gap-x-6 gap-y-2 text-xs">
          <div>
            <dt className="text-slate-500">Progress</dt>
            <dd className="mt-0.5 font-mono font-semibold text-slate-100">{decidedCount} / {groupCount} sets</dd>
          </div>
          <div>
            <dt className="text-slate-500">Files in review</dt>
            <dd className="mt-0.5 font-mono font-semibold text-slate-100">{fileCount.toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Selected removals</dt>
            <dd className="mt-0.5 font-mono font-semibold text-rose-300">{selectedRemovalCount.toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Potential space</dt>
            <dd className="mt-0.5 flex items-center gap-1 font-mono font-semibold text-amber-300">
              <HardDrive className="h-3.5 w-3.5" /> {formatBytes(estimatedReclaim)}
            </dd>
          </div>
        </dl>

        <div className="flex items-center gap-2">
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
      <Progress value={progress} className="h-1 rounded-none bg-slate-800 [&>div]:bg-amber-400" />
    </header>
  )
}
