import { useMemo, useState } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDashed,
  Search,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { FileCard } from '@/components/FileCard'
import { formatBytes } from '@/lib/format'
import type { Decision, DuplicateGroup, Strategy, VideoFile } from '@/types'

const PAGE_SIZE = 12

type SortKey = 'name' | 'size' | 'resolution' | 'coverage' | 'path'

type ReviewWorkspaceProps = {
  group: DuplicateGroup
  decision?: Decision
  busy: boolean
  previousGroupId?: number
  nextGroupId?: number
  onDecision: (decision: Decision) => void
  onClearDecision: (groupId: number) => void
  onRecommend: (groupId: number, strategy: Strategy) => void
  onNavigate: (groupId: number) => void
  onOpenInFolder: (file: VideoFile) => Promise<void>
  onMoveToFolder: (file: VideoFile) => Promise<void>
}

function sortFiles(files: VideoFile[], sort: SortKey): VideoFile[] {
  return [...files].sort((left, right) => {
    if (sort === 'size') return right.sizeBytes - left.sizeBytes
    if (sort === 'resolution') return right.width * right.height - left.width * left.height
    if (sort === 'coverage') return right.coveredPercent - left.coveredPercent
    if (sort === 'path') return left.path.localeCompare(right.path)
    return left.name.localeCompare(right.name)
  })
}

export function ReviewWorkspace({
  group,
  decision,
  busy,
  previousGroupId,
  nextGroupId,
  onDecision,
  onClearDecision,
  onRecommend,
  onNavigate,
  onOpenInFolder,
  onMoveToFolder,
}: ReviewWorkspaceProps) {
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SortKey>('resolution')
  const [page, setPage] = useState(1)
  const [strategy, setStrategy] = useState<Strategy>('delete-fully-covered')

  const keeperIds = useMemo(
    () => new Set(decision?.keeperIds ?? group.files.map((file) => file.id)),
    [decision, group.files],
  )
  const visibleFiles = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const filtered = needle
      ? group.files.filter(
          (file) =>
            file.name.toLowerCase().includes(needle) ||
            file.path.toLowerCase().includes(needle),
        )
      : group.files
    return sortFiles(filtered, sort)
  }, [group.files, query, sort])
  const pageCount = Math.max(1, Math.ceil(visibleFiles.length / PAGE_SIZE))
  const pageFiles = visibleFiles.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const removedFiles = group.files.filter((file) => !keeperIds.has(file.id))
  const estimatedReclaim = removedFiles.reduce((sum, file) => sum + file.sizeBytes, 0)

  function updateKeepers(nextKeepers: Set<number>, method = 'web-manual') {
    onDecision({ groupId: group.id, keeperIds: [...nextKeepers], method })
  }

  function toggleFile(fileId: number) {
    const next = new Set(keeperIds)
    if (next.has(fileId)) {
      if (next.size === 1) {
        toast.warning('Every set must keep at least one file.')
        return
      }
      next.delete(fileId)
    } else {
      next.add(fileId)
    }
    updateKeepers(next)
  }

  return (
    <main id="review-workspace" tabIndex={-1} className="min-w-0 flex-1 bg-background scroll-mt-4 lg:overflow-y-auto">
      <div className="border-b border-stone-200 bg-white px-4 py-5 lg:px-6 lg:py-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm font-semibold uppercase tracking-[0.14em] text-slate-500">
                Set {group.id}
              </span>
              {decision ? (
                <Badge className="border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-50">
                  <CheckCircle2 className="mr-1 h-3.5 w-3.5" aria-hidden="true" /> Reviewed
                </Badge>
              ) : (
                <Badge variant="outline" className="text-slate-500">
                  <CircleDashed className="mr-1 h-3.5 w-3.5" aria-hidden="true" /> Needs review
                </Badge>
              )}
            </div>
            <h2 className="mt-2 text-2xl font-semibold leading-tight tracking-tight text-slate-950 lg:text-3xl">
              Compare {group.fileCount} related videos
            </h2>
            <p className="mt-2 max-w-3xl text-base leading-relaxed text-slate-600">
              Checked files are kept. Unchecked files are added to the plan only when coverage is safe.
            </p>
          </div>
          <nav className="flex items-center gap-2" aria-label="Duplicate set navigation">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!previousGroupId}
              onClick={() => previousGroupId && onNavigate(previousGroupId)}
            >
              <ArrowLeft className="mr-1.5 h-4 w-4" /> Previous
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!nextGroupId}
              onClick={() => nextGroupId && onNavigate(nextGroupId)}
            >
              Next <ArrowRight className="ml-1.5 h-4 w-4" />
            </Button>
          </nav>
        </div>

        {!decision && (
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50/80 px-4 py-3.5 text-base shadow-sm">
            <div>
              <p className="font-semibold text-amber-950">Safe default: keep everything</p>
              <p className="text-amber-800">This set stays untouched until you record a decision.</p>
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="border-amber-300 bg-white"
              onClick={() => updateKeepers(new Set(group.files.map((file) => file.id)), 'web-keep-all')}
            >
              <ShieldCheck className="mr-2 h-4 w-4" aria-hidden="true" /> Mark reviewed — keep all
            </Button>
          </div>
        )}
      </div>

      <section className="border-b border-stone-200 bg-slate-100/70 px-4 py-4 lg:px-6" aria-label="Recommendation controls">
        <div className="flex flex-wrap items-center gap-3">
          <span className="mr-1 flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-slate-600">
            <Sparkles className="h-4 w-4 text-amber-600" aria-hidden="true" /> Quick recommendation
          </span>
          <Select value={strategy} onValueChange={(value) => setStrategy(value as Strategy)}>
            <SelectTrigger className="w-full bg-white sm:w-[250px]" aria-label="Recommendation strategy">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="delete-fully-covered">Prefer covering videos</SelectItem>
              <SelectItem value="delete-shallower">Prefer deeper folders</SelectItem>
              <SelectItem value="delete-shorter-name">Prefer descriptive names</SelectItem>
              <SelectItem value="delete-numbered-name">Prefer clean names</SelectItem>
            </SelectContent>
          </Select>
          <Button type="button" size="sm" disabled={busy} onClick={() => onRecommend(group.id, strategy)}>
            {busy ? 'Calculating…' : 'Apply to this set'}
          </Button>
          {decision && (
            <Button type="button" size="sm" variant="ghost" onClick={() => onClearDecision(group.id)}>
              Reset to unresolved
            </Button>
          )}
          <div className="ml-auto grid grid-cols-3 overflow-hidden rounded-lg border border-slate-200 bg-white text-right text-sm shadow-sm">
            <div className="px-3 py-2"><span className="block text-xs text-slate-500">Keep</span><strong className="font-mono text-base">{keeperIds.size}</strong></div>
            <div className="border-x border-slate-200 px-3 py-2"><span className="block text-xs text-slate-500">Quarantine</span><strong className="font-mono text-base text-rose-700">{removedFiles.length}</strong></div>
            <div className="px-3 py-2"><span className="block text-xs text-slate-500">Potential space</span><strong className="font-mono text-base">{formatBytes(estimatedReclaim)}</strong></div>
          </div>
        </div>
      </section>

      <div className="px-4 py-5 lg:px-6 lg:py-6">
        <div className="mb-5 flex flex-wrap items-center gap-3 rounded-xl border border-stone-200 bg-white p-3 surface-shadow">
          <label className="relative min-w-[240px] flex-1" htmlFor="file-search">
            <span className="sr-only">Search files in this set</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" aria-hidden="true" />
            <Input
              id="file-search"
              type="search"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
                setPage(1)
              }}
              placeholder="Find a file in this set"
              className="border-slate-200 bg-slate-50/70 pl-9 shadow-none"
            />
          </label>
          <Select
            value={sort}
            onValueChange={(value) => {
              setSort(value as SortKey)
              setPage(1)
            }}
          >
            <SelectTrigger className="w-full border-slate-200 bg-slate-50/70 shadow-none sm:w-[210px]" aria-label="Sort files">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="resolution">Highest resolution</SelectItem>
              <SelectItem value="size">Largest file</SelectItem>
              <SelectItem value="coverage">Highest coverage</SelectItem>
              <SelectItem value="name">File name</SelectItem>
              <SelectItem value="path">Full path</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {pageFiles.length === 0 ? (
          <div className="border border-dashed border-stone-300 bg-white px-6 py-16 text-center text-base text-slate-600" role="status">
            No files match your search in this set.
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2 2xl:grid-cols-3">
            {pageFiles.map((file) => (
              <FileCard
                key={file.id}
                file={file}
                kept={keeperIds.has(file.id)}
                canRemove={keeperIds.size > 1}
                onToggle={() => toggleFile(file.id)}
                onKeepOnly={() => updateKeepers(new Set([file.id]))}
                onCopied={() => toast.success('Path copied')}
                onOpenInFolder={() => onOpenInFolder(file)}
                onMoveToFolder={() => onMoveToFolder(file)}
              />
            ))}
          </div>
        )}

        {pageCount > 1 && (
          <nav className="mt-5 flex flex-col items-start justify-between gap-3 border-t border-stone-300 pt-4 sm:flex-row sm:items-center" aria-label="Files pagination">
            <p className="text-base text-slate-600">
              Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, visibleFiles.length)} of {visibleFiles.length}
            </p>
            <div className="flex items-center gap-2">
              <Button type="button" size="sm" variant="outline" disabled={page === 1} onClick={() => setPage((value) => value - 1)}>
                <ChevronLeft className="mr-1 h-4 w-4" /> Previous page
              </Button>
              <span className="font-mono text-sm text-slate-600">{page} / {pageCount}</span>
              <Button type="button" size="sm" variant="outline" disabled={page === pageCount} onClick={() => setPage((value) => value + 1)}>
                Next page <ChevronRight className="ml-1 h-4 w-4" />
              </Button>
            </div>
          </nav>
        )}
      </div>
    </main>
  )
}
