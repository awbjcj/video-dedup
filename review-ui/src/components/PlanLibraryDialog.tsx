import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { fetchPlans, loadSavedPlan, renameSavedPlan } from '@/lib/api'
import type { PlanPage, SavedPlan } from '@/lib/api'
import type { SessionPayload } from '@/types'

type Props = { dirty: boolean; onClose: () => void; onLoad: (session: SessionPayload) => void }

export function PlanLibraryDialog({ dirty, onClose, onLoad }: Props) {
  const [page, setPage] = useState(1)
  const [data, setData] = useState<PlanPage | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState<SavedPlan | null>(null)
  const [name, setName] = useState('')
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    let cancelled = false
    fetchPlans(page).then((result) => { if (!cancelled) setData(result) })
      .catch((reason: Error) => { if (!cancelled) setError(reason.message) })
    return () => { cancelled = true }
  }, [page, revision])

  async function act(plan: SavedPlan, rename: boolean) {
    setBusy(true)
    setError('')
    try {
      if (rename) {
        await renameSavedPlan(plan, name.trim())
        setEditing(null)
        setData(null)
        setRevision((value) => value + 1)
        toast.success('Plan renamed')
      } else {
        onLoad(await loadSavedPlan(plan))
        toast.success(`Loaded ${plan.name}`)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not update the saved plan.')
    } finally {
      setBusy(false)
    }
  }

  return <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose() }}>
    <DialogContent className="max-w-3xl rounded-xl bg-[#fbfaf7]">
      <DialogHeader>
        <DialogTitle>Saved plans</DialogTitle>
        <DialogDescription>Resume decisions from any saved run. Each plan includes its scan data and review settings.</DialogDescription>
      </DialogHeader>
      {dirty && <p className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">Save your current decisions before loading another plan.</p>}
      {error && <div role="alert" className="text-sm text-red-700">{error} <Button variant="outline" disabled={busy} onClick={() => { setError(''); setData(null); setRevision((value) => value + 1) }}>Retry</Button></div>}
      {!data && !error && <p role="status">Loading saved plans…</p>}
      {data?.total === 0 && <div className="rounded-lg border border-dashed p-8 text-center"><p className="font-medium">No saved plans yet</p><p className="mt-2 text-sm text-slate-600">Use Save plan to name and preserve your decisions.</p></div>}
      <div className="space-y-3" aria-busy={busy}>
        {data?.items.map((plan) => <article key={`${plan.runId}/${plan.id}`} className="min-w-0 rounded-lg border bg-white p-4">
          <div className="flex flex-col items-start justify-between gap-3 sm:flex-row">
            <div className="min-w-0 w-full flex-1">
              <h3 className="break-words font-semibold">{plan.name}</h3>
              <p className="mt-1 text-sm text-slate-600">{new Date(plan.createdAt).toLocaleString()} · {plan.decisionCount} reviewed sets</p>
              <p className="mt-2 break-all text-xs text-slate-500">Run {plan.runId}</p>
              <p className="mt-1 break-all text-xs text-slate-500">{plan.roots.join(', ')}</p>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" disabled={busy} aria-label={`Rename ${plan.name}`} onClick={() => { setEditing(plan); setName(plan.name); setError('') }}>Rename</Button>
              <Button disabled={dirty || busy} aria-label={`Load ${plan.name}`} onClick={() => void act(plan, false)}>Load</Button>
            </div>
          </div>
          {editing?.id === plan.id && <form className="mt-3 space-y-2 border-t pt-3" onSubmit={(event) => { event.preventDefault(); void act(plan, true) }}>
            <label htmlFor="rename-plan" className="text-sm font-medium">New plan name</label>
            <Input autoFocus id="rename-plan" maxLength={120} value={name} disabled={busy} onChange={(event) => setName(event.target.value)} />
            <div className="flex gap-2"><Button type="submit" disabled={busy || !name.trim()}>{busy ? 'Saving…' : 'Save name'}</Button><Button type="button" variant="outline" disabled={busy} onClick={() => setEditing(null)}>Cancel</Button></div>
          </form>}
        </article>)}
      </div>
      {data && data.total > data.pageSize && <div className="flex items-center justify-between gap-2">
        <Button variant="outline" disabled={busy || page === 1} onClick={() => { setData(null); setError(''); setEditing(null); setPage(page - 1) }}>Previous</Button>
        <span className="text-sm">Page {page} of {Math.ceil(data.total / data.pageSize)}</span>
        <Button variant="outline" disabled={busy || page * data.pageSize >= data.total} onClick={() => { setData(null); setError(''); setEditing(null); setPage(page + 1) }}>Next</Button>
      </div>}
    </DialogContent>
  </Dialog>
}
