import { useEffect, useMemo, useReducer, useState } from 'react'
import { AlertCircle, LoaderCircle, RefreshCw } from 'lucide-react'
import { toast, Toaster } from 'sonner'

import { AppHeader } from '@/components/AppHeader'
import { ApplyReviewedDialog } from '@/components/ApplyReviewedDialog'
import { BulkToolbar } from '@/components/BulkToolbar'
import { DetectionSettingsDialog } from '@/components/DetectionSettingsDialog'
import { ReviewSidebar } from '@/components/ReviewSidebar'
import { ReviewWorkspace } from '@/components/ReviewWorkspace'
import { SavePlanDialog } from '@/components/SavePlanDialog'
import { Button } from '@/components/ui/button'
import {
  applyReviewed,
  fetchRecommendations,
  fetchRescanStatus,
  fetchSession,
  moveToFolder,
  openInFolder,
  savePlan,
  startRescan,
  updateSettings,
} from '@/lib/api'
import { formatBytes } from '@/lib/format'
import { updateLinkedGroupSelection } from '@/lib/groupSelection'
import { filterReviewGroups } from '@/lib/reviewGroups'
import type { Decision, DetectionSettings, FilterStatus, RescanStatus, SessionPayload, Strategy, VideoFile } from '@/types'

type ReviewState = {
  decisions: Map<number, Decision>
  history: Map<number, Decision>[]
  dirty: boolean
}

type ReviewAction =
  | { type: 'hydrate'; decisions: Decision[] }
  | { type: 'set-many'; decisions: Decision[] }
  | { type: 'clear-many'; groupIds: number[] }
  | { type: 'undo' }
  | { type: 'saved' }

function reviewReducer(state: ReviewState, action: ReviewAction): ReviewState {
  if (action.type === 'hydrate') {
    return {
      decisions: new Map(action.decisions.map((decision) => [decision.groupId, decision])),
      history: [],
      dirty: false,
    }
  }
  if (action.type === 'set-many') {
    const next = new Map(state.decisions)
    action.decisions.forEach((decision) => next.set(decision.groupId, decision))
    return { decisions: next, history: [...state.history.slice(-29), state.decisions], dirty: true }
  }
  if (action.type === 'clear-many') {
    const next = new Map(state.decisions)
    action.groupIds.forEach((groupId) => next.delete(groupId))
    return { decisions: next, history: [...state.history.slice(-29), state.decisions], dirty: true }
  }
  if (action.type === 'undo') {
    const previous = state.history.at(-1)
    if (!previous) return state
    return { decisions: previous, history: state.history.slice(0, -1), dirty: true }
  }
  return { ...state, dirty: false, history: [] }
}

function App() {
  const [session, setSession] = useState<SessionPayload | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [activeGroupId, setActiveGroupId] = useState(1)
  const [selectedGroupIds, setSelectedGroupIds] = useState<Set<number>>(new Set())
  const [groupQuery, setGroupQuery] = useState('')
  const [filter, setFilter] = useState<FilterStatus>('unresolved')
  const [bulkStrategy, setBulkStrategy] = useState<Strategy>('delete-fully-covered')
  const [recommending, setRecommending] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)
  const [applyingReviewed, setApplyingReviewed] = useState(false)
  const [applyDialogOpen, setApplyDialogOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [applyingSettings, setApplyingSettings] = useState(false)
  const [rescanStatus, setRescanStatus] = useState<RescanStatus>({ state: 'idle' })
  const [review, dispatch] = useReducer(reviewReducer, {
    decisions: new Map(),
    history: [],
    dirty: false,
  })

  useEffect(() => {
    let cancelled = false
    fetchSession()
      .then((payload) => {
        if (cancelled) return
        setSession(payload)
        dispatch({ type: 'hydrate', decisions: payload.initialDecisions })
        const firstUnresolved = payload.groups.find(
          (group) => !payload.initialDecisions.some((decision) => decision.groupId === group.id),
        )
        setActiveGroupId(firstUnresolved?.id ?? payload.groups[0]?.id ?? 1)
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(error instanceof Error ? error.message : 'Could not load review data.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (rescanStatus.state !== 'running') return
    const timer = window.setInterval(() => {
      fetchRescanStatus()
        .then(async (status) => {
          setRescanStatus(status)
          if (status.state !== 'completed') return
          const payload = await fetchSession()
          setSession(payload)
          dispatch({ type: 'hydrate', decisions: payload.initialDecisions })
          setSelectedGroupIds(new Set())
          setActiveGroupId(payload.groups[0]?.id ?? 1)
          toast.success('Rescan complete', { description: 'The review now uses the updated detection settings.' })
        })
        .catch((error: unknown) => {
          setRescanStatus({ state: 'failed', message: error instanceof Error ? error.message : 'Could not read rescan status.' })
        })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [rescanStatus.state])

  useEffect(() => {
    function warnBeforeClose(event: BeforeUnloadEvent) {
      if (!review.dirty && !applyingReviewed) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeClose)
    return () => window.removeEventListener('beforeunload', warnBeforeClose)
  }, [applyingReviewed, review.dirty])

  useEffect(() => {
    function saveShortcut(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        setSaveDialogOpen(true)
      }
    }
    window.addEventListener('keydown', saveShortcut)
    return () => window.removeEventListener('keydown', saveShortcut)
  }, [])

  const navigableGroups = useMemo(
    () => session ? filterReviewGroups(session.groups, review.decisions, filter, groupQuery) : [],
    [filter, groupQuery, review.decisions, session],
  )
  const activeGroup = session?.groups.find((group) => group.id === activeGroupId)
  const activeGroupIndex = session?.groups.findIndex((group) => group.id === activeGroupId) ?? -1
  const navigableGroupIds = new Set(navigableGroups.map((group) => group.id))
  const previousGroupId = activeGroupIndex > 0
    ? session?.groups
        .slice(0, activeGroupIndex)
        .reverse()
        .find((group) => navigableGroupIds.has(group.id))?.id
    : undefined
  const nextGroupId = activeGroupIndex >= 0
    ? session?.groups
        .slice(activeGroupIndex + 1)
        .find((group) => navigableGroupIds.has(group.id))?.id
    : undefined

  function updateGroupQuery(value: string) {
    setGroupQuery(value)
    if (!session) return
    const matchingGroups = filterReviewGroups(session.groups, review.decisions, filter, value)
    if (matchingGroups.length && !matchingGroups.some((group) => group.id === activeGroupId)) {
      setActiveGroupId(matchingGroups[0].id)
    }
  }

  function updateFilter(value: FilterStatus) {
    setFilter(value)
    if (!session) return
    const matchingGroups = filterReviewGroups(session.groups, review.decisions, value, groupQuery)
    if (matchingGroups.length && !matchingGroups.some((group) => group.id === activeGroupId)) {
      setActiveGroupId(matchingGroups[0].id)
    }
  }

  const selectedRemovalCount = useMemo(() => {
    if (!session) return 0
    return [...review.decisions.values()].reduce((total, decision) => {
      const group = session.groups.find((item) => item.id === decision.groupId)
      return total + Math.max(0, (group?.fileCount ?? 0) - decision.keeperIds.length)
    }, 0)
  }, [review.decisions, session])
  const estimatedReclaim = useMemo(() => {
    if (!session) return 0
    return [...review.decisions.values()].reduce((total, decision) => {
      const keepers = new Set(decision.keeperIds)
      const group = session.groups.find((item) => item.id === decision.groupId)
      return total + (group?.files.reduce((sum, file) => sum + (keepers.has(file.id) ? 0 : file.sizeBytes), 0) ?? 0)
    }, 0)
  }, [review.decisions, session])
  const actionableReviewedSetCount = useMemo(() => {
    if (!session) return 0
    return [...review.decisions.values()].filter((decision) => {
      const group = session.groups.find((item) => item.id === decision.groupId)
      return (group?.fileCount ?? 0) > decision.keeperIds.length
    }).length
  }, [review.decisions, session])

  async function applyRecommendation(groupIds: number[], strategy: Strategy) {
    if (!groupIds.length) return
    setRecommending(true)
    try {
      const recommendations = await fetchRecommendations(groupIds, strategy)
      dispatch({ type: 'set-many', decisions: recommendations })
      toast.success(`Updated ${recommendations.length} set${recommendations.length === 1 ? '' : 's'}`, {
        description: 'Review the selected keepers before saving the plan.',
      })
    } catch (error) {
      toast.error('Could not calculate recommendations', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    } finally {
      setRecommending(false)
    }
  }

  function keepAllSelected() {
    if (!session) return
    const decisions = session.groups
      .filter((group) => selectedGroupIds.has(group.id))
      .map((group) => ({
        groupId: group.id,
        keeperIds: group.files.map((file) => file.id),
        method: 'web-keep-all',
      }))
    dispatch({ type: 'set-many', decisions })
    toast.success(`Marked ${decisions.length} sets as reviewed — keep all`)
  }

  async function confirmSave() {
    setSaving(true)
    try {
      const result = await savePlan([...review.decisions.values()])
      dispatch({ type: 'saved' })
      setSaveDialogOpen(false)
      toast.success(`Plan saved with ${result.actionCount} safe removal${result.actionCount === 1 ? '' : 's'}`, {
        description: `${formatBytes(result.reclaimBytes)} planned for quarantine. No files have changed.`,
        duration: 7000,
      })
    } catch (error) {
      toast.error('Plan was not saved', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    } finally {
      setSaving(false)
    }
  }

  async function confirmApplyReviewed() {
    setApplyingReviewed(true)
    try {
      const result = await applyReviewed([...review.decisions.values()])
      setSession(result.session)
      dispatch({ type: 'hydrate', decisions: result.session.initialDecisions })
      setSelectedGroupIds(new Set())
      setFilter('unresolved')
      setActiveGroupId(result.session.groups[0]?.id ?? 1)
      setApplyDialogOpen(false)
      if (result.failedFileCount) {
        toast.warning(`Applied ${result.appliedSetCount} reviewed set${result.appliedSetCount === 1 ? '' : 's'} with refusals`, {
          description: `${result.appliedFileCount} file${result.appliedFileCount === 1 ? '' : 's'} moved; ${result.failedSetCount} set${result.failedSetCount === 1 ? '' : 's'} remain in the plan.`,
          duration: 9000,
        })
      } else {
        toast.success(`Applied and cleared ${result.appliedSetCount} reviewed set${result.appliedSetCount === 1 ? '' : 's'}`, {
          description: `${result.appliedFileCount} file${result.appliedFileCount === 1 ? '' : 's'} moved to quarantine, reclaiming ${formatBytes(result.reclaimBytes)}.`,
          duration: 8000,
        })
      }
    } catch (error) {
      toast.error('Reviewed sets were not applied', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    } finally {
      setApplyingReviewed(false)
    }
  }

  async function revealVideo(file: VideoFile) {
    try {
      await openInFolder(file.id)
      toast.success('Opened in file manager', { description: file.name })
    } catch (error) {
      toast.error('Could not open the file location', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    }
  }

  async function moveVideo(file: VideoFile) {
    try {
      const result = await moveToFolder(file.id)
      if (result.cancelled) return
      if (!result.moved) {
        toast.info('File is already in that folder', { description: file.name })
        return
      }
      if (result.session) setSession(result.session)
      toast.success('Video moved', { description: result.destinationPath })
    } catch (error) {
      toast.error('Could not move the video', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    }
  }

  async function applyReviewSettings(settings: Omit<DetectionSettings, 'rescanAvailable' | 'reportMinimumDuplicatePercent'>) {
    setApplyingSettings(true)
    try {
      const payload = await updateSettings(settings)
      setSession(payload)
      dispatch({ type: 'hydrate', decisions: payload.initialDecisions })
      setSelectedGroupIds(new Set())
      setActiveGroupId(payload.groups[0]?.id ?? 1)
      toast.success('Review settings applied', {
        description: `${payload.summary.groupCount.toLocaleString()} duplicate sets match the current filters.`,
      })
    } catch (error) {
      toast.error('Settings were not applied', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    } finally {
      setApplyingSettings(false)
    }
  }

  async function rescanWithSettings(settings: Omit<DetectionSettings, 'rescanAvailable' | 'reportMinimumDuplicatePercent'>) {
    try {
      const status = await startRescan(settings)
      setRescanStatus(status)
      toast.info('Rescan started', { description: 'Cached fingerprints will be reused when possible.' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error'
      setRescanStatus({ state: 'failed', message })
      toast.error('Rescan could not start', { description: message })
    }
  }

  if (loadError) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-[#f4f1ea] p-6">
        <div className="w-full max-w-lg border border-rose-200 bg-white p-8 text-center shadow-sm">
          <AlertCircle className="mx-auto h-9 w-9 text-rose-600" />
          <h1 className="mt-4 text-2xl font-semibold text-slate-950">Review data could not be loaded</h1>
          <p className="mt-2 text-base text-slate-600">{loadError}</p>
          <Button type="button" className="mt-5" onClick={() => window.location.reload()}>
            <RefreshCw className="mr-2 h-4 w-4" /> Try again
          </Button>
        </div>
      </div>
    )
  }

  if (!session) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-slate-950 text-slate-300">
        <div className="text-center">
          <LoaderCircle className="mx-auto h-8 w-8 animate-spin text-amber-400" />
          <p className="mt-3 text-base">Preparing duplicate sets and safe coverage data…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-dvh flex-col bg-background lg:h-dvh lg:min-h-[640px] lg:overflow-hidden">
      <a
        href="#review-workspace"
        className="sr-only z-[100] rounded-md bg-white px-4 py-2 font-semibold text-slate-950 shadow-lg focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        Skip to review workspace
      </a>
      <AppHeader
        reportPath={session.reportPath}
        planPath={session.planPath}
        groupCount={session.summary.groupCount}
        fileCount={session.summary.fileCount}
        filteredShortFileCount={session.summary.filteredShortFileCount}
        minimumDuration={session.minimumDuration}
        decidedCount={review.decisions.size}
        selectedRemovalCount={selectedRemovalCount}
        estimatedReclaim={estimatedReclaim}
        dirty={review.dirty}
        canUndo={review.history.length > 0}
        canApply={actionableReviewedSetCount > 0}
        saving={saving}
        applying={applyingReviewed}
        onUndo={() => dispatch({ type: 'undo' })}
        onOpenSettings={() => setSettingsOpen(true)}
        onApply={() => setApplyDialogOpen(true)}
        onSave={() => setSaveDialogOpen(true)}
      />

      {activeGroup ? <div className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[21rem_auto] lg:grid-cols-[350px_minmax(0,1fr)] lg:grid-rows-1 xl:grid-cols-[370px_minmax(0,1fr)]">
        <ReviewSidebar
          groups={session.groups}
          decisions={review.decisions}
          activeGroupId={activeGroupId}
          selectedGroupIds={selectedGroupIds}
          query={groupQuery}
          filter={filter}
          onQueryChange={updateGroupQuery}
          onFilterChange={updateFilter}
          onActivate={setActiveGroupId}
          onToggleSelected={(groupId) =>
            setSelectedGroupIds((current) =>
              updateLinkedGroupSelection(
                session.groups,
                current,
                [groupId],
                !current.has(groupId),
              ),
            )
          }
          onSelectVisible={(groupIds, selected) =>
            setSelectedGroupIds((current) =>
              updateLinkedGroupSelection(session.groups, current, groupIds, selected),
            )
          }
        />

        <div className="flex min-h-0 min-w-0 flex-col">
          <BulkToolbar
            selectedCount={selectedGroupIds.size}
            strategy={bulkStrategy}
            busy={recommending}
            onStrategyChange={setBulkStrategy}
            onApplyStrategy={() => void applyRecommendation([...selectedGroupIds], bulkStrategy)}
            onKeepAll={keepAllSelected}
            onClear={() => dispatch({ type: 'clear-many', groupIds: [...selectedGroupIds] })}
          />
          <ReviewWorkspace
            key={activeGroup.id}
            group={activeGroup}
            decision={review.decisions.get(activeGroup.id)}
            busy={recommending}
            previousGroupId={previousGroupId}
            nextGroupId={nextGroupId}
            onDecision={(decision) => dispatch({ type: 'set-many', decisions: [decision] })}
            onClearDecision={(groupId) => dispatch({ type: 'clear-many', groupIds: [groupId] })}
            onRecommend={(groupId, strategy) => void applyRecommendation([groupId], strategy)}
            onNavigate={setActiveGroupId}
            onOpenInFolder={revealVideo}
            onMoveToFolder={moveVideo}
          />
        </div>
      </div> : (
        <main className="flex flex-1 items-center justify-center p-6">
          <div className="max-w-xl border border-stone-300 bg-white p-8 text-center shadow-sm" role="status">
            <AlertCircle className="mx-auto h-9 w-9 text-amber-700" aria-hidden="true" />
            <h2 className="mt-4 text-xl font-semibold text-slate-950">No matches meet these settings</h2>
            <p className="mt-2 text-base leading-relaxed text-slate-600">
              Lower the minimum duplicated timeline or minimum duration in Settings to bring more pairs back into review.
            </p>
            <Button type="button" className="mt-5" onClick={() => setSettingsOpen(true)}>
              Adjust settings
            </Button>
          </div>
        </main>
      )}

      {settingsOpen ? <DetectionSettingsDialog
        open={settingsOpen}
        settings={session.settings}
        applying={applyingSettings}
        hasUnsavedChanges={review.dirty}
        rescanStatus={rescanStatus}
        onOpenChange={setSettingsOpen}
        onApplyReviewSettings={(settings) => void applyReviewSettings(settings)}
        onRescan={(settings) => void rescanWithSettings(settings)}
      /> : null}

      <SavePlanDialog
        open={saveDialogOpen}
        saving={saving}
        planPath={session.planPath}
        decidedCount={review.decisions.size}
        groupCount={session.summary.groupCount}
        removalCount={selectedRemovalCount}
        estimatedReclaim={estimatedReclaim}
        onOpenChange={setSaveDialogOpen}
        onConfirm={() => void confirmSave()}
      />
      <ApplyReviewedDialog
        open={applyDialogOpen}
        applying={applyingReviewed}
        reviewedSetCount={actionableReviewedSetCount}
        removalCount={selectedRemovalCount}
        estimatedReclaim={estimatedReclaim}
        onOpenChange={setApplyDialogOpen}
        onConfirm={() => void confirmApplyReviewed()}
      />
      <Toaster position="bottom-right" richColors closeButton />
    </div>
  )
}

export default App
