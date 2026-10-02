import type { RescanStatus } from '@/types'

export function OperationProgress({ title, status }: { title: string; status: RescanStatus }) {
  if (status.state === 'idle') return null
  const measurable = typeof status.total === 'number' && status.total > 0
  return <section className="shrink-0 border-b border-stone-200 bg-white px-5 py-3" aria-label={`${title} progress`}>
    <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
      <strong>{title} · {status.state}</strong>
      {measurable ? <span className="font-mono">{status.completed ?? 0} / {status.total}</span> : null}
    </div>
    {status.state === 'running' ? <progress className="mt-2 h-2 w-full accent-amber-600" aria-label={`${title} progress`} max={measurable ? status.total! : undefined} value={measurable ? status.completed ?? 0 : undefined} /> : null}
    <p className="mt-1 break-all text-sm text-slate-700" role="status">{status.message}</p>
  </section>
}
