import { ArchiveRestore, FileWarning, ShieldCheck } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatBytes } from '@/lib/format'

type ApplyReviewedDialogProps = {
  open: boolean
  applying: boolean
  reviewedSetCount: number
  removalCount: number
  estimatedReclaim: number
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
}

export function ApplyReviewedDialog({
  open,
  applying,
  reviewedSetCount,
  removalCount,
  estimatedReclaim,
  onOpenChange,
  onConfirm,
}: ApplyReviewedDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl rounded-xl border-slate-200 bg-[#fbfaf7] surface-shadow-strong">
        <DialogHeader>
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-xl bg-rose-100 text-rose-800">
            <ArchiveRestore className="h-5 w-5" aria-hidden="true" />
          </div>
          <DialogTitle>Quarantine reviewed removals?</DialogTitle>
          <DialogDescription>
            This applies only reviewed sets that contain a coverage-safe removal. Unreviewed sets stay untouched.
          </DialogDescription>
        </DialogHeader>

        <dl className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border bg-slate-200 text-base sm:grid-cols-3">
          <div className="bg-white p-4"><dt className="text-slate-600">Reviewed sets</dt><dd className="mt-1 font-mono font-semibold">{reviewedSetCount}</dd></div>
          <div className="bg-white p-4"><dt className="text-slate-600">Selected files</dt><dd className="mt-1 font-mono font-semibold">{removalCount}</dd></div>
          <div className="bg-white p-4"><dt className="text-slate-600">Estimated space</dt><dd className="mt-1 font-mono font-semibold">{formatBytes(estimatedReclaim)}</dd></div>
        </dl>

        <div className="flex gap-3 border-l-4 border-rose-500 bg-rose-50 p-4 text-base text-rose-950">
          <FileWarning className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <p>
            Files are moved to a timestamped quarantine beside the plan. The server checks each file's size and
            modification time first; refused sets remain in the plan.
          </p>
        </div>

        <div className="flex gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-base text-emerald-950">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <p>Successfully applied sets are removed from the active plan and review queue.</p>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" disabled={applying} onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" variant="destructive" disabled={applying} onClick={onConfirm}>
            <ArchiveRestore className="mr-2 h-4 w-4" aria-hidden="true" />
            {applying ? 'Moving to quarantine…' : 'Quarantine reviewed sets'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
