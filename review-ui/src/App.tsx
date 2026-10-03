import { useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { AlertCircle, LoaderCircle, RefreshCw } from 'lucide-react'
import { toast, Toaster } from 'sonner'

import { OperationProgress } from '@/components/OperationProgress'
import { AppHeader } from '@/components/AppHeader'
import { ApplyReviewedDialog } from '@/components/ApplyReviewedDialog'
import { BulkToolbar } from '@/components/BulkToolbar'
import { DetectionSettingsDialog } from '@/components/DetectionSettingsDialog'
import { ReviewSidebar } from '@/components/ReviewSidebar'
import { ReviewWorkspace } from '@/components/ReviewWorkspace'
import { SavePlanDialog } from '@/components/SavePlanDialog'
import { PlanLibraryDialog } from '@/components/PlanLibraryDialog'
import { Button } from '@/components/ui/button'
import {
  applyReviewed,
  fetchApplyStatus,
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
import { updateGroupSelection } from '@/lib/groupSelection'
import { filterReviewGroups } from '@/lib/reviewGroups'
import { removalFiles, updateDecisions } from '@/lib/reviewDecisions'
import type { Decision, DetectionSettings, DuplicateGroup, FilterStatus, RescanStatus, SessionPayload, Strategy, VideoFile } from '@/types'

type ReviewState = {
  decisions: Map<number, Decision>
  history: Map<number, Decision>[]
  dirty: boolean
}

type ReviewAction =
  | { type: 'hydrate'; decisions: Decision[] }
  | { type: 'set-many'; decisions: Decision[]; groups: DuplicateGroup[] }
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
    const next = updateDecisions(action.groups, state.decisions, action.decisions)
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
  const pendingScanRefresh = useRef(false)
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
  const [plansOpen, setPlansOpen] = useState(false)
  const [applyingReviewed, setApplyingReviewed] = useState(false)
  const [applyDialogOpen, setApplyDialogOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [applyingSettings, setApplyingSettings] = useState(false)
  const [applyStatus, setApplyStatus] = useState<RescanStatus>({ state: 'idle' })
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
    let cancelled = false
    let timer: number
    let wasRunning = false
    async function poll() {
      try {
        const [scan, removal] = await Promise.all([fetchRescanStatus(), fetchApplyStatus()])
        if (cancelled) return
        const running = scan.state === 'running' || removal.state === 'running'
        if ((wasRunning || pendingScanRefresh.current) && !running) {
          const payload = await fetchSession()
          if (cancelled) return
          pendingScanRefresh.current = false
          setSession(payload)
          dispatch({ type: 'hydrate', decisions: payload.initialDecisions })
          setSelectedGroupIds(new Set())
          setActiveGroupId(payload.groups[0]?.id ?? 1)
        }
        setRescanStatus(scan)
        setApplyStatus(removal)
        wasRunning = running
      } catch {
        // Keep the last known operation state; reconnect on the next poll.
      } finally {
        if (!cancelled) timer = window.setTimeout(() => void poll(), 1000)
      }
    }
    void poll()
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [])

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

  const selectedRemovalFiles = useMemo(
    () => removalFiles(session?.groups ?? [], review.decisions),
    [review.decisions, session],
  )
  const selectedRemovalCount = selectedRemovalFiles.size
  const estimatedReclaim = [...selectedRemovalFiles.values()].reduce((sum, file) => sum + file.sizeBytes, 0)
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
      dispatch({ type: 'set-many', decisions: recommendations, groups: session?.groups ?? [] })
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
    dispatch({ type: 'set-many', decisions, groups: session.groups })
    toast.success(`Marked ${decisions.length} sets as reviewed — keep all`)
  }

  async function confirmSave(name: string) {
    setSaving(true)
    try {
      const result = await savePlan([...review.decisions.values()], name)
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

  async function confirmApplyReviewed(permanent: boolean, confirmation: string) {
    setApplyingReviewed(true)
    try {
      const result = await applyReviewed([...review.decisions.values()], permanent, confirmation)
      setSession(result.session)
      dispatch({ type: 'hydrate', decisions: result.session.initialDecisions })
      setSelectedGroupIds(new Set())
      setFilter('unresolved')
      setActiveGroupId(result.session.groups[0]?.id ?? 1)
      setApplyDialogOpen(false)
      if (result.failedFileCount) {
        toast.warning(`Applied ${result.appliedSetCount} reviewed set${result.appliedSetCount === 1 ? '' : 's'} with refusals`, {
          description: `${result.appliedFileCount} file${result.appliedFileCount === 1 ? '' : 's'} ${permanent ? 'deleted' : 'quarantined'}; ${result.failedSetCount} set${result.failedSetCount === 1 ? '' : 's'} remain in the plan.`,
          duration: 9000,
        })
      } else {
        toast.success(`Applied and cleared ${result.appliedSetCount} reviewed set${result.appliedSetCount === 1 ? '' : 's'}`, {
          description: `${result.appliedFileCount} file${result.appliedFileCount === 1 ? '' : 's'} ${permanent ? 'permanently deleted' : 'moved to quarantine'} (${formatBytes(result.reclaimBytes)}).`,
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
      setRescanStatus({ state: 'running', message: 'Starting scan…' })
      const status = await startRescan(settings)
      pendingScanRefresh.current = true
      setRescanStatus(status)
      toast.info('Rescan started', { description: 'Cached fingerprints will be reused when possible.' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error'
      setRescanStatus({ state: 'failed', message })
      toast.error('Rescan could not start', { description: message })
    }
  }

  const operationBusy = applyingReviewed || rescanStatus.state === 'running' || applyStatus.state === 'running'

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
        canUndo={review.history.length > 0 && !operationBusy}
        canApply={actionableReviewedSetCount > 0 && !operationBusy}
        saving={saving || operationBusy}
        applying={operationBusy}
        onUndo={() => dispatch({ type: 'undo' })}
        onOpenSettings={() => setSettingsOpen(true)}
        onApply={() => setApplyDialogOpen(true)}
        onSave={() => setSaveDialogOpen(true)}
        onOpenPlans={() => setPlansOpen(true)}
      />

      <OperationProgress title="Scan" status={rescanStatus} />
      <OperationProgress title="File removal" status={applyStatus} />
      <fieldset disabled={operationBusy} className="contents">
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
              updateGroupSelection(
                session.groups,
                current,
                [groupId],
                !current.has(groupId),
              ),
            )
          }
          onSelectVisible={(groupIds, selected) =>
            setSelectedGroupIds((current) =>
              updateGroupSelection(session.groups, current, groupIds, selected),
            )
          }
        />

        <div className="flex min-h-0 min-w-0 flex-col">
          <BulkToolbar
            selectedCount={selectedGroupIds.size}
            strategy={bulkStrategy}
            busy={recommending || operationBusy}
            onStrategyChange={setBulkStrategy}
            onApplyStrategy={() => void applyRecommendation([...selectedGroupIds], bulkStrategy)}
            onKeepAll={keepAllSelected}
            onClear={() => dispatch({ type: 'clear-many', groupIds: [...selectedGroupIds] })}
          />
          <ReviewWorkspace
            key={activeGroup.id}
            group={activeGroup}
            decision={review.decisions.get(activeGroup.id)}
            removalIds={new Set(selectedRemovalFiles.keys())}
            busy={recommending || operationBusy}
            previousGroupId={previousGroupId}
            nextGroupId={nextGroupId}
            onDecision={(decision) => dispatch({ type: 'set-many', decisions: [decision], groups: session.groups })}
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

      </fieldset>
      {settingsOpen ? <DetectionSettingsDialog
        open={settingsOpen}
        settings={session.settings}
        applying={applyingSettings || operationBusy}
        hasUnsavedChanges={review.dirty}
        rescanStatus={rescanStatus}
        onOpenChange={setSettingsOpen}
        onApplyReviewSettings={(settings) => void applyReviewSettings(settings)}
        onRescan={(settings) => void rescanWithSettings(settings)}
      /> : null}

      {plansOpen && <PlanLibraryDialog dirty={review.dirty || rescanStatus.state === 'running'} onClose={() => setPlansOpen(false)} onLoad={(payload) => {
        setSession(payload)
        dispatch({ type: 'hydrate', decisions: payload.initialDecisions })
        setSelectedGroupIds(new Set())
        setActiveGroupId(payload.groups[0]?.id ?? 1)
        setFilter('all')
        setGroupQuery('')
        setPlansOpen(false)
      }} />}
      {saveDialogOpen && <SavePlanDialog
        open={saveDialogOpen}
        saving={saving || operationBusy}
        planPath={session.planPath}
        decidedCount={review.decisions.size}
        groupCount={session.summary.groupCount}
        removalCount={selectedRemovalCount}
        estimatedReclaim={estimatedReclaim}
        onOpenChange={setSaveDialogOpen}
        onConfirm={(name) => void confirmSave(name)}
      />}
      {applyDialogOpen ? <ApplyReviewedDialog
        open={applyDialogOpen}
        applying={operationBusy}
        reviewedSetCount={actionableReviewedSetCount}
        removalCount={selectedRemovalCount}
        estimatedReclaim={estimatedReclaim}
        onOpenChange={setApplyDialogOpen}
        status={applyStatus}
        onConfirm={(permanent, confirmation) => void confirmApplyReviewed(permanent, confirmation)}
      /> : null}
      <Toaster position="bottom-right" richColors closeButton />
    </div>
  )
}

export default App
