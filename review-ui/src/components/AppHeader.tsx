import { ArchiveRestore, HardDrive, Save, Settings2, ShieldCheck, Undo2, Video } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { formatBytes, shortPath } from '@/lib/format'

type AppHeaderProps = {
  reportPath: string
  planPath: string
  groupCount: number
  fileCount: number
  filteredShortFileCount: number
  minimumDuration: number
  decidedCount: number
  selectedRemovalCount: number
  estimatedReclaim: number
  dirty: boolean
  canUndo: boolean
  canApply: boolean
  saving: boolean
  applying: boolean
  onUndo: () => void
  onOpenSettings: () => void
  onApply: () => void
  onSave: () => void
}
export function AppHeader({
  reportPath,
  planPath,
  groupCount,
  fileCount,
  filteredShortFileCount,
  minimumDuration,
  decidedCount,
  selectedRemovalCount,
  estimatedReclaim,
  dirty,
  canUndo,
  canApply,
  saving,
  applying,
  onUndo,
  onOpenSettings,
  onApply,
  onSave,
}: AppHeaderProps) {
  const progress = groupCount ? (decidedCount / groupCount) * 100 : 0

  return (
    <header className="relative z-20 border-b border-slate-800 bg-[#080f1e] text-white shadow-lg shadow-slate-950/10">
      <div className="grid items-center gap-4 px-4 py-4 sm:grid-cols-[minmax(0,1fr)_auto] lg:px-6 xl:grid-cols-[minmax(270px,1fr)_minmax(500px,1.65fr)_auto] xl:gap-6">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-amber-400 text-slate-950 shadow-[0_8px_24px_rgb(251_191_36_/_0.18)]">
            <Video className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="whitespace-nowrap text-lg font-semibold tracking-tight">Video Dedup Review</h1>
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

        <dl className="col-span-full grid grid-cols-2 overflow-hidden rounded-lg border border-slate-800 bg-slate-900/55 text-sm sm:grid-cols-4 xl:col-span-1">
          <div className="border-b border-r border-slate-800 px-3 py-2.5 sm:border-b-0">
            <dt className="text-xs font-medium text-slate-400">Review progress</dt>
            <dd className="mt-0.5 font-mono font-semibold text-slate-100">{decidedCount} / {groupCount} sets</dd>
          </div>
          <div className="border-b border-slate-800 px-3 py-2.5 sm:border-b-0 sm:border-r">
            <dt className="text-xs font-medium text-slate-400">Files in review</dt>
            <dd className="mt-0.5 font-mono font-semibold text-slate-100">{fileCount.toLocaleString()}</dd>
            {filteredShortFileCount > 0 ? (
              <dd className="mt-0.5 text-xs text-slate-400">
                {filteredShortFileCount.toLocaleString()} clips under {minimumDuration.toLocaleString()} sec hidden
              </dd>
            ) : null}
          </div>
          <div className="border-r border-slate-800 px-3 py-2.5">
            <dt className="text-xs font-medium text-slate-400">Planned quarantine</dt>
            <dd className="mt-0.5 font-mono font-semibold text-rose-300">{selectedRemovalCount.toLocaleString()}</dd>
          </div>
          <div className="px-3 py-2.5">
            <dt className="text-xs font-medium text-slate-400">Potential space</dt>
            <dd className="mt-0.5 flex items-center gap-1 font-mono font-semibold text-amber-300">
              <HardDrive className="h-3.5 w-3.5" aria-hidden="true" /> {formatBytes(estimatedReclaim)}
            </dd>
          </div>
        </dl>

        <div className="flex flex-wrap items-center justify-end gap-1.5 sm:ml-auto">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={saving || applying}
            onClick={onOpenSettings}
            className="text-slate-300 hover:bg-slate-800 hover:text-white"
          >
            <Settings2 className="mr-2 h-4 w-4" aria-hidden="true" /> Settings
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={!canUndo || saving || applying}
            onClick={onUndo}
            className="text-slate-300 hover:bg-slate-800 hover:text-white"
          >
            <Undo2 className="mr-2 h-4 w-4" aria-hidden="true" /> Undo
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!canApply || saving || applying}
            onClick={onApply}
            className="border-rose-300 bg-transparent text-rose-200 hover:bg-rose-950/50 hover:text-rose-100"
            title="Apply the reviewed part of the plan"
          >
            <ArchiveRestore className="mr-2 h-4 w-4" aria-hidden="true" />
            {applying ? 'Applying…' : 'Apply reviewed'}
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={saving || applying}
            onClick={onSave}
            className="bg-amber-400 text-slate-950 hover:bg-amber-300"
            title={`Save to ${planPath}`}
          >
            {saving ? <ShieldCheck className="mr-2 h-4 w-4 animate-pulse" aria-hidden="true" /> : <Save className="mr-2 h-4 w-4" aria-hidden="true" />}
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
