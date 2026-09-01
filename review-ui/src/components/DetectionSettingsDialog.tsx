import { useMemo, useState } from 'react'
import { Info, LoaderCircle, ScanSearch, ShieldCheck, SlidersHorizontal } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { DetectionSettings, RescanStatus } from '@/types'

type EditableSettings = Omit<DetectionSettings, 'rescanAvailable' | 'reportMinimumDuplicatePercent'>

type DetectionSettingsDialogProps = {
  open: boolean
  settings: DetectionSettings
  applying: boolean
  hasUnsavedChanges: boolean
  rescanStatus: RescanStatus
  onOpenChange: (open: boolean) => void
  onApplyReviewSettings: (settings: EditableSettings) => void
  onRescan: (settings: EditableSettings) => void
}

type NumberFieldProps = {
  id: string
  label: string
  description: string
  value: number
  min: number
  max?: number
  step?: number
  disabled?: boolean
  onChange: (value: number) => void
}

function NumberField({
  id,
  label,
  description,
  value,
  min,
  max,
  step = 1,
  disabled,
  onChange,
}: NumberFieldProps) {
  const descriptionId = `${id}-description`
  return (
    <div className="grid gap-2 border-b border-stone-200 pb-4 last:border-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_8rem] sm:items-center">
      <div>
        <Label htmlFor={id} className="text-base font-semibold text-slate-900">{label}</Label>
        <p id={descriptionId} className="mt-1 text-sm leading-relaxed text-slate-600">{description}</p>
      </div>
      <Input
        id={id}
        type="number"
        value={Number.isNaN(value) ? '' : value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        aria-describedby={descriptionId}
        onChange={(event) => onChange(event.currentTarget.value === '' ? Number.NaN : event.currentTarget.valueAsNumber)}
        className="bg-white font-mono text-base"
      />
    </div>
  )
}

function editable(settings: DetectionSettings): EditableSettings {
  const {
    rescanAvailable: _rescanAvailable,
    reportMinimumDuplicatePercent: _reportMinimumDuplicatePercent,
    ...values
  } = settings
  return values
}

export function DetectionSettingsDialog({
  open,
  settings,
  applying,
  hasUnsavedChanges,
  rescanStatus,
  onOpenChange,
  onApplyReviewSettings,
  onRescan,
}: DetectionSettingsDialogProps) {
  const [draft, setDraft] = useState<EditableSettings>(() => editable(settings))

  const validationMessage = useMemo(() => {
    const values = Object.values(draft)
    if (values.some((value) => !Number.isFinite(value))) return 'Every setting needs a valid number.'
    if (draft.minimumDuplicatePercent < 0 || draft.minimumDuplicatePercent > 100) return 'Duplicate percentage must be from 0 to 100.'
    if (draft.minimumDeleteCoverage < 0 || draft.minimumDeleteCoverage > 100) return 'Delete coverage must be from 0 to 100.'
    if (draft.minimumDuration < 0) return 'Minimum video duration cannot be negative.'
    if (draft.sampleInterval <= 0) return 'Sample interval must be greater than zero.'
    if (draft.minimumSegment <= 0) return 'Matching segment must be greater than zero.'
    if (draft.hashDistance < 0 || draft.hashDistance > 136) return 'Watermark tolerance must be from 0 to 136.'
    return null
  }, [draft])

  const loweringBelowReport = draft.minimumDuplicatePercent < settings.reportMinimumDuplicatePercent
  const scanChanged = draft.sampleInterval !== settings.sampleInterval
    || draft.minimumSegment !== settings.minimumSegment
    || draft.hashDistance !== settings.hashDistance
    || loweringBelowReport
  const reviewChanged = draft.minimumDuplicatePercent !== settings.minimumDuplicatePercent
    || draft.minimumDeleteCoverage !== settings.minimumDeleteCoverage
    || draft.minimumDuration !== settings.minimumDuration
  const rescanning = rescanStatus.state === 'running'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[calc(100dvh-2rem)] max-w-3xl flex-col gap-0 overflow-hidden border-slate-200 bg-[#fbfaf7] p-0">
        <DialogHeader className="shrink-0 border-b border-stone-200 px-5 py-5 sm:px-6">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-md bg-amber-100 text-amber-900">
            <SlidersHorizontal className="h-5 w-5" aria-hidden="true" />
          </div>
          <DialogTitle>Detection and safety settings</DialogTitle>
          <DialogDescription>
            Tune which matches appear, how tolerant scanning is to watermarks, and how much coverage is required before removal.
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-7 overflow-y-auto px-5 py-5 sm:px-6">
          <fieldset>
            <legend className="mb-1 text-sm font-semibold uppercase tracking-wide text-amber-800">Current review</legend>
            <p className="mb-4 text-sm text-slate-600">These settings can be applied immediately to the existing report. Lowering duplicate coverage below the report's scan threshold requires a rescan.</p>
            <div className="space-y-4 rounded-md border border-stone-200 bg-white p-4">
              <NumberField
                id="minimum-duplicate-percent"
                label="Minimum duplicated timeline"
                description="Keep a pair when either video is duplicated by at least this percentage. Use 95 for a near-duplicate view that still preserves contained clips."
                value={draft.minimumDuplicatePercent}
                min={0}
                max={100}
                step={0.1}
                disabled={rescanning}
                onChange={(minimumDuplicatePercent) => setDraft((current) => ({ ...current, minimumDuplicatePercent }))}
              />
              <NumberField
                id="minimum-video-duration"
                label="Minimum video duration (seconds)"
                description="Hide shorter clips from review. Set this to 0 to include every duration."
                value={draft.minimumDuration}
                min={0}
                step={0.5}
                disabled={rescanning}
                onChange={(minimumDuration) => setDraft((current) => ({ ...current, minimumDuration }))}
              />
              <NumberField
                id="minimum-delete-coverage"
                label="Deletion safety coverage"
                description="A file stays safe unless selected keepers cover at least this much of its timeline. The recommended default is 95%."
                value={draft.minimumDeleteCoverage}
                min={0}
                max={100}
                step={0.1}
                disabled={rescanning}
                onChange={(minimumDeleteCoverage) => setDraft((current) => ({ ...current, minimumDeleteCoverage }))}
              />
            </div>
          </fieldset>

          <fieldset>
            <legend className="mb-1 text-sm font-semibold uppercase tracking-wide text-amber-800">Scan accuracy</legend>
            <p className="mb-4 text-sm text-slate-600">Changing these values requires rescanning the report. Cached fingerprints are reused when possible.</p>
            <div className="space-y-4 rounded-md border border-stone-200 bg-white p-4">
              <NumberField
                id="watermark-tolerance"
                label="Watermark and re-encode tolerance"
                description="Perceptual hash distance. Larger values tolerate stronger overlays and encoding changes, but can introduce more false positives. Default: 20."
                value={draft.hashDistance}
                min={0}
                max={136}
                disabled={rescanning}
                onChange={(hashDistance) => setDraft((current) => ({ ...current, hashDistance }))}
              />
              <NumberField
                id="sample-interval"
                label="Frame sample interval (seconds)"
                description="Smaller spacing improves timing accuracy and costs more scan time and report space. Default: 3 seconds."
                value={draft.sampleInterval}
                min={0.1}
                step={0.1}
                disabled={rescanning}
                onChange={(sampleInterval) => setDraft((current) => ({ ...current, sampleInterval }))}
              />
              <NumberField
                id="minimum-match-segment"
                label="Minimum matching segment (seconds)"
                description="Ignore isolated visual matches shorter than this continuous duration. Default: 9 seconds."
                value={draft.minimumSegment}
                min={0.1}
                step={0.5}
                disabled={rescanning}
                onChange={(minimumSegment) => setDraft((current) => ({ ...current, minimumSegment }))}
              />
            </div>
          </fieldset>

          <div className="flex gap-3 border-l-4 border-sky-500 bg-sky-50 p-4 text-sm leading-relaxed text-sky-950" role="note">
            <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <p>Percent duplicated measures matched timeline coverage, not pixel similarity. Watermark tolerance decides whether sampled frames count as matches.</p>
          </div>

          {rescanStatus.message ? (
            <div className="flex gap-3 border border-stone-200 bg-white p-4 text-sm text-slate-700" role="status" aria-live="polite">
              {rescanning ? <LoaderCircle className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-amber-700" aria-hidden="true" /> : <ScanSearch className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" aria-hidden="true" />}
              <p>{rescanStatus.message}</p>
            </div>
          ) : null}

          {hasUnsavedChanges ? (
            <div className="flex gap-3 border-l-4 border-amber-500 bg-amber-50 p-4 text-sm leading-relaxed text-amber-950" role="alert">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <p>Save or undo your current review changes before applying new filters or starting a rescan.</p>
            </div>
          ) : null}

          {validationMessage ? <p className="text-sm font-medium text-rose-700" role="alert">{validationMessage}</p> : null}
        </div>

        <DialogFooter className="shrink-0 border-t border-stone-200 bg-white px-5 py-4 sm:px-6">
          <Button type="button" variant="outline" disabled={applying || rescanning} onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={Boolean(validationMessage) || !reviewChanged || loweringBelowReport || hasUnsavedChanges || applying || rescanning}
            onClick={() => onApplyReviewSettings(draft)}
          >
            <ShieldCheck className="mr-2 h-4 w-4" aria-hidden="true" />
            {applying ? 'Applying…' : 'Apply to review'}
          </Button>
          <Button
            type="button"
            disabled={Boolean(validationMessage) || !settings.rescanAvailable || hasUnsavedChanges || applying || rescanning || (!scanChanged && !reviewChanged)}
            onClick={() => onRescan(draft)}
          >
            {rescanning ? <LoaderCircle className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : <ScanSearch className="mr-2 h-4 w-4" aria-hidden="true" />}
            {rescanning ? 'Rescanning…' : 'Rescan with all settings'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
