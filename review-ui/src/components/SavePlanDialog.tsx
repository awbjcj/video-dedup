import { AlertTriangle, FileCheck2, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { Input } from '@/components/ui/input'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatBytes, shortPath } from '@/lib/format'

type SavePlanDialogProps = {
  open: boolean
  saving: boolean
  planPath: string
  decidedCount: number
  groupCount: number
  removalCount: number
  estimatedReclaim: number
  onOpenChange: (open: boolean) => void
  onConfirm: (name: string) => void
}
export function SavePlanDialog({
  open,
  saving,
  planPath,
  decidedCount,
  groupCount,
  removalCount,
  estimatedReclaim,
  onOpenChange,
  onConfirm,
}: SavePlanDialogProps) {
  const unresolved = groupCount - decidedCount
  const [name, setName] = useState(() => `Review ${new Date().toLocaleString()}`)

  return (
    <Dialog open={open} onOpenChange={(value) => { if (!saving) onOpenChange(value) }}>
      <DialogContent className="max-w-xl rounded-xl border-slate-200 bg-[#fbfaf7] surface-shadow-strong">
        <DialogHeader>
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-xl bg-amber-100 text-amber-800">
            <FileCheck2 className="h-5 w-5" aria-hidden="true" />
          </div>
          <DialogTitle>Save this review plan?</DialogTitle>
          <DialogDescription>
            This writes a JSON plan only. No video is moved or deleted until you run the separate apply command.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <label htmlFor="plan-name" className="text-sm font-medium">Plan name</label>
          <Input id="plan-name" value={name} maxLength={120} disabled={saving} onChange={(event) => setName(event.target.value)} aria-describedby="plan-name-help" />
          <p id="plan-name-help" className="text-sm text-slate-600">Saves a new snapshot with your decisions and scan settings. Find it later in Saved plans.</p>
        </div>

        <dl className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border bg-slate-200 text-base sm:grid-cols-2">
          <div className="bg-white p-4"><dt className="text-slate-600">Reviewed sets</dt><dd className="mt-1 font-mono font-semibold">{decidedCount} / {groupCount}</dd></div>
          <div className="bg-white p-4"><dt className="text-slate-600">Planned selections</dt><dd className="mt-1 font-mono font-semibold">{removalCount} files</dd></div>
          <div className="bg-white p-4"><dt className="text-slate-600">Estimated space</dt><dd className="mt-1 font-mono font-semibold">{formatBytes(estimatedReclaim)}</dd></div>
          <div className="bg-white p-4"><dt className="text-slate-600">Unreviewed kept safe</dt><dd className="mt-1 font-mono font-semibold">{unresolved} sets</dd></div>
        </dl>

        {unresolved > 0 && (
          <div className="flex gap-3 border-l-4 border-amber-400 bg-amber-50 p-4 text-base text-amber-950">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <p><strong>{unresolved} sets still need review.</strong> Shared files keep the selections made in other sets. You can reopen this plan later and continue reviewing.</p>
          </div>
        )}

        <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
          <p className="text-sm font-medium text-slate-600">Plan destination</p>
          <p className="mt-1 break-all font-mono text-sm leading-relaxed text-slate-800" title={planPath}>{shortPath(planPath, 120)}</p>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" disabled={saving} onClick={() => onOpenChange(false)}>
            Continue reviewing
          </Button>
          <Button type="button" disabled={saving || !name.trim()} onClick={() => onConfirm(name.trim())}>
            <ShieldCheck className="mr-2 h-4 w-4" aria-hidden="true" /> {saving ? 'Saving plan…' : 'Save plan safely'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
