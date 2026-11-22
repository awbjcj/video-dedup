import { useEffect, useRef, useState } from 'react'
import { Headphones } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { requestJson } from '@/lib/api'
import type { DuplicateGroup } from '@/types'

type Budget = {
  remaining_micros: number
  spent_micros: number
  reserved_micros: number
  threshold: string
}
type Availability = { enabled: boolean; reason?: string; budget?: Budget; maxClipPairs: number }
type Transcript = { text: string; languages: string[]; cached: boolean; accounting: string }
type Evidence = {
  aId: number; bId: number; aName: string; bName: string
  aStartSeconds?: number; bStartSeconds?: number; durationSeconds?: number
  status: string; reason: string; aTranscript?: Transcript; bTranscript?: Transcript
}
type Result = { evidence: Evidence[]; partial: boolean; budget: Budget; notice: string }

const labels: Record<string, string> = {
  exact_file: 'Identical file bytes', identical_audio: 'Matching decoded audio',
  missing_audio: 'Missing audio track', silent_audio: 'Silent interval',
  different_language: 'Different speech languages', different_speech: 'Different wording',
  similar_speech: 'Similar wording · audio differs', unknown: 'Inconclusive',
  alignment_unavailable: 'New scan needed', unavailable: 'Review paused',
}
const dollars = (micros: number) => `$${(micros / 1_000_000).toFixed(4)}`
const time = (seconds: number) => `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(1).padStart(4, '0')}`

export function AudioReviewPanel({ group }: { group: DuplicateGroup }) {
  const [availability, setAvailability] = useState<Availability>()
  const [result, setResult] = useState<Result>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // Initial cache/status responses must never replace a newer user-requested review.
  const reviewStarted = useRef(false)
  const identity = { groupId: group.id, groupKey: group.audioReviewKey }

  useEffect(() => {
    let active = true
    requestJson<Availability>('/api/audio-review/availability')
      .then((value) => { if (active && !reviewStarted.current) setAvailability(value) })
      .catch((reason: Error) => { if (active) setError(reason.message) })
    if (group.audioReviewKey) {
      requestJson<{ result?: Result }>('/api/audio-review/saved', {
        method: 'POST', body: JSON.stringify({ groupId: group.id, groupKey: group.audioReviewKey }),
      }).then((value) => { if (active && !reviewStarted.current) setResult(value.result) })
        .catch((reason: Error) => { if (active) setError(reason.message) })
    }
    return () => { active = false }
  }, [group.id, group.audioReviewKey])

  async function review() {
    reviewStarted.current = true
    setBusy(true)
    setError('')
    try {
      const value = await requestJson<Result>('/api/audio-review', {
        method: 'POST', body: JSON.stringify({ ...identity, confirmUpload: true }),
      })
      setResult(value)
      setAvailability((previous) => previous && { ...previous, budget: value.budget })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Audio review failed.')
    } finally {
      setBusy(false)
    }
  }

  const budget = availability?.budget || result?.budget
  return (
    <section aria-label="Audio difference review" className="border-b border-stone-200 bg-white px-4 py-4 lg:px-6">
      <details>
        <summary className="cursor-pointer text-sm font-semibold text-slate-700">
          <Headphones className="mr-2 inline h-4 w-4" aria-hidden="true" /> Optional audio difference review
        </summary>
        <div className="mt-3 space-y-3 text-sm text-slate-600">
          <p>Compare speech in visually matched intervals. Clicking below sends matched audio clips to OpenAI.
            Local checks and cached transcripts are reused. Keep and quarantine choices remain under your control.</p>
          {availability?.enabled ? (
            <>
              <p>Up to {availability.maxClipPairs} clip pairs per review, with each clip limited to 60 seconds.</p>
              <Button type="button" size="sm" variant="outline" disabled={busy || !group.audioReviewKey}
                onClick={() => { void review() }}>
                {busy ? 'Reviewing matched audio…' : 'Send matched audio for review'}
              </Button>
            </>
          ) : <p>{availability?.reason || 'Checking audio review availability…'}</p>}
          {busy && <p role="status">This may take a few minutes. File moves, rescans and apply are paused during review.</p>}
          {budget && <p className="font-mono text-xs">Audio budget: {dollars(budget.remaining_micros)} available · {dollars(budget.spent_micros)} spent · {dollars(budget.reserved_micros)} held · {budget.threshold}</p>}
          {error && <p role="alert" className="text-rose-700">{error}</p>}
          {result && (
            <div className="space-y-3" aria-live="polite">
              <p>{result.notice}</p>
              {result.partial && <p className="font-medium text-amber-800">Partial review: some intervals remain unchecked. A review limit or unavailable request stopped further processing.</p>}
              {result.evidence.map((entry, index) => (
                <article key={`${entry.aId}-${entry.bId}-${index}`} className="rounded-lg border border-slate-200 p-3">
                  <p className="font-semibold text-slate-900">{labels[entry.status] || 'Inconclusive'}</p>
                  <p className="mt-1 break-words">{entry.aName} ↔ {entry.bName}</p>
                  {entry.aStartSeconds !== undefined && entry.bStartSeconds !== undefined && (
                    <p className="font-mono text-xs">{time(entry.aStartSeconds)} ↔ {time(entry.bStartSeconds)} · {entry.durationSeconds}s</p>
                  )}
                  <p className="mt-1">{entry.reason}</p>
                  {[entry.aTranscript, entry.bTranscript].map((transcript, side) => transcript && (
                    <div key={side} className="mt-2 rounded bg-slate-50 p-2">
                      <p className="text-xs font-semibold">{side === 0 ? entry.aName : entry.bName} · {transcript.languages.join(', ') || 'Language unknown'}{transcript.cached ? ' · cached' : ''}{transcript.accounting === 'held' ? ' · billing pending' : ''}</p>
                      <p className="mt-1 whitespace-pre-wrap break-words">{transcript.text || 'No speech recognized.'}</p>
                    </div>
                  ))}
                </article>
              ))}
            </div>
          )}
        </div>
      </details>
    </section>
  )
}
