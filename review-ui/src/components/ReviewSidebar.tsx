import { useMemo } from 'react'
import { CheckCircle2, CircleDashed, FileVideo2, Layers3, Search } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import type { Decision, DuplicateGroup, FilterStatus } from '@/types'

type ReviewSidebarProps = {
  groups: DuplicateGroup[]
  decisions: Map<number, Decision>
  activeGroupId: number
  selectedGroupIds: Set<number>
  query: string
  filter: FilterStatus
  onQueryChange: (value: string) => void
  onFilterChange: (value: FilterStatus) => void
  onActivate: (groupId: number) => void
  onToggleSelected: (groupId: number) => void
  onSelectVisible: (groupIds: number[], selected: boolean) => void
}
export function ReviewSidebar({
  groups,
  decisions,
  activeGroupId,
  selectedGroupIds,
  query,
  filter,
  onQueryChange,
  onFilterChange,
  onActivate,
  onToggleSelected,
  onSelectVisible,
}: ReviewSidebarProps) {
  const visibleGroups = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return groups.filter((group) => {
      const isDecided = decisions.has(group.id)
      if (filter === 'decided' && !isDecided) return false
      if (filter === 'unresolved' && isDecided) return false
      if (!needle) return true
      return (
        String(group.id).includes(needle) ||
        group.files.some(
          (file) =>
            file.name.toLowerCase().includes(needle) ||
            file.path.toLowerCase().includes(needle),
        )
      )
    })
  }, [decisions, filter, groups, query])

  const allVisibleSelected =
    visibleGroups.length > 0 && visibleGroups.every((group) => selectedGroupIds.has(group.id))

  return (
    <aside className="flex min-h-0 flex-col border-r border-slate-800 bg-[#0b1323] text-slate-100">
      <div className="border-b border-slate-800 px-4 py-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.14em] text-amber-400">
              Review queue
            </p>
            <h2 className="mt-0.5 text-xl font-semibold tracking-tight">Duplicate sets</h2>
          </div>
          <Badge className="border-slate-700 bg-slate-950/70 text-slate-300 hover:bg-slate-950/70">
            {visibleGroups.length} shown
          </Badge>
        </div>

        <label className="relative block" htmlFor="group-search">
          <span className="sr-only">Search duplicate sets</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
          <Input
            id="group-search"
            type="search"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Search file or path"
            className="border-slate-700 bg-slate-950/70 pl-9 text-slate-100 placeholder:text-slate-500 focus-visible:ring-amber-400"
          />
        </label>

        <div className="mt-3 grid grid-cols-3 gap-1 rounded-lg border border-slate-800 bg-slate-950/60 p-1" role="group" aria-label="Filter sets">
          {(['all', 'unresolved', 'decided'] as const).map((value) => (
            <Button
              key={value}
              type="button"
              size="sm"
              variant="ghost"
              className={cn(
                'h-9 px-2 capitalize text-slate-300 hover:bg-slate-800 hover:text-slate-100',
                filter === value && 'bg-slate-700 text-white shadow-sm hover:bg-slate-700',
              )}
              aria-pressed={filter === value}
              onClick={() => onFilterChange(value)}
            >
              {value === 'unresolved' ? 'To review' : value}
            </Button>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between border-b border-slate-800 bg-slate-950/20 px-4 py-3 text-sm text-slate-300">
        <label className="flex cursor-pointer items-center gap-2" htmlFor="select-visible-groups">
          <Checkbox
            id="select-visible-groups"
            checked={allVisibleSelected}
            onCheckedChange={(checked) =>
              onSelectVisible(
                visibleGroups.map((group) => group.id),
                checked === true,
              )
            }
            className="border-slate-500 data-[state=checked]:border-amber-400 data-[state=checked]:bg-amber-400 data-[state=checked]:text-slate-950"
          />
          Select visible
        </label>
        <span>{selectedGroupIds.size} selected</span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto" aria-label="Duplicate set list">
        {visibleGroups.length === 0 ? (
          <div className="px-6 py-12 text-center text-base text-slate-400" role="status">
            <Layers3 className="mx-auto mb-3 h-7 w-7" />
            No sets match this filter.
          </div>
        ) : (
          <ul className="divide-y divide-slate-800/70">
            {visibleGroups.map((group) => {
              const decision = decisions.get(group.id)
              const isActive = group.id === activeGroupId
              return (
                <li
                  key={group.id}
                  className={cn(
                    'group flex items-start gap-3 border-l-[3px] px-3 py-3.5 transition-colors',
                    isActive
                      ? 'border-l-amber-400 bg-slate-800/80 shadow-[inset_0_1px_rgb(255_255_255_/_0.03)]'
                      : 'border-l-transparent hover:bg-slate-900/70',
                  )}
                >
                  <Checkbox
                    checked={selectedGroupIds.has(group.id)}
                    onCheckedChange={() => onToggleSelected(group.id)}
                    aria-label={`Select set ${group.id} for bulk actions`}
                    className="mt-1 border-slate-600 data-[state=checked]:border-amber-400 data-[state=checked]:bg-amber-400 data-[state=checked]:text-slate-950"
                  />
                  <button
                    type="button"
                    onClick={() => onActivate(group.id)}
                    aria-current={isActive ? 'true' : undefined}
                    className="min-w-0 flex-1 rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
                  >
                    <span className="flex items-center justify-between gap-3">
                      <span className="font-mono text-sm font-semibold text-slate-100">
                        Set {group.id}
                      </span>
                      {decision ? (
                        <span className="flex items-center gap-1 text-xs font-medium text-emerald-400">
                          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" /> Reviewed
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-xs font-medium text-slate-400">
                          <CircleDashed className="h-3.5 w-3.5" aria-hidden="true" /> Needs review
                        </span>
                      )}
                    </span>
                    <span className="mt-2 flex items-center gap-1.5 text-sm text-slate-300">
                      <FileVideo2 className="h-3.5 w-3.5" aria-hidden="true" />
                      {group.fileCount} files · {group.matchCount} matches
                    </span>
                    <span className="mt-1 block truncate text-sm text-slate-400">
                      {group.files[0]?.name}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </aside>
  )
}
