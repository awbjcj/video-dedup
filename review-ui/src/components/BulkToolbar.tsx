import { RotateCcw, ShieldCheck, Sparkles } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { Strategy } from '@/types'

const strategyLabels: Record<Strategy, string> = {
  'delete-shallower': 'Prefer deeper folders',
  'delete-shorter-name': 'Prefer descriptive names',
  'delete-numbered-name': 'Prefer clean names',
  'delete-fully-covered': 'Prefer covering videos',
}
type BulkToolbarProps = {
  selectedCount: number
  strategy: Strategy
  busy: boolean
  onStrategyChange: (strategy: Strategy) => void
  onApplyStrategy: () => void
  onKeepAll: () => void
  onClear: () => void
}

export function BulkToolbar({
  selectedCount,
  strategy,
  busy,
  onStrategyChange,
  onApplyStrategy,
  onKeepAll,
  onClear,
}: BulkToolbarProps) {
  if (selectedCount === 0) return null

  return (
    <section
      aria-label="Bulk actions"
      className="flex flex-wrap items-center gap-3 border-b border-amber-200 bg-gradient-to-r from-amber-50 to-white px-4 py-4 shadow-sm lg:px-6"
    >
      <div className="mr-auto flex items-center gap-2">
        <span className="flex h-9 min-w-9 items-center justify-center rounded-full bg-slate-950 px-2 font-mono text-sm font-bold text-amber-300 shadow-sm">
          {selectedCount}
        </span>
        <div>
          <p className="text-base font-semibold text-slate-900">sets selected</p>
          <p className="text-sm text-slate-600">Apply one decision rule to the whole selection.</p>
        </div>
      </div>

      <Select value={strategy} onValueChange={(value) => onStrategyChange(value as Strategy)}>
        <SelectTrigger className="w-full border-amber-300 bg-white sm:w-[245px]" aria-label="Bulk recommendation">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.entries(strategyLabels) as [Strategy, string][]).map(([value, label]) => (
            <SelectItem key={value} value={value}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button type="button" size="sm" className="flex-1 sm:flex-none" onClick={onApplyStrategy} disabled={busy}>
        <Sparkles className="mr-2 h-4 w-4" aria-hidden="true" />
        {busy ? 'Calculating…' : 'Apply recommendation'}
      </Button>
      <Button type="button" size="sm" variant="outline" className="flex-1 sm:flex-none" onClick={onKeepAll} disabled={busy}>
        <ShieldCheck className="mr-2 h-4 w-4" aria-hidden="true" /> Keep all
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={onClear} disabled={busy}>
        <RotateCcw className="mr-2 h-4 w-4" aria-hidden="true" /> Clear reviews
      </Button>
    </section>
  )
}
