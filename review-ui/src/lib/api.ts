import type {
  ApplyReviewedResult,
  Decision,
  DetectionSettings,
  MoveToFolderResult,
  OpenInFolderResult,
  RescanStatus,
  SaveResult,
  SessionPayload,
  Strategy,
} from '@/types'

async function requestJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Video-Dedup-Review': '1',
      ...options?.headers,
    },
  })
  const payload = (await response.json()) as T & { error?: string }
  if (!response.ok) {
    throw new Error(payload.error || `Request failed with status ${response.status}`)
  }
  return payload
}

export function fetchSession(): Promise<SessionPayload> {
  return requestJson<SessionPayload>('/api/session')
}

export async function fetchRecommendations(
  groupIds: number[],
  strategy: Strategy,
): Promise<Decision[]> {
  const payload = await requestJson<{ ok: true; decisions: Decision[] }>(
    '/api/recommendations',
    {
      method: 'POST',
      body: JSON.stringify({ groupIds, strategy }),
    },
  )
  return payload.decisions
}

export function savePlan(decisions: Decision[], name?: string): Promise<SaveResult> {
  return requestJson<SaveResult>('/api/plan', {
    method: 'POST',
    body: JSON.stringify({ decisions, name }),
  })
}

export type SavedPlan = {
  id: string
  runId: string
  name: string
  createdAt: string
  updatedAt: string
  decisionCount: number
  roots: string[]
}

export type PlanPage = { items: SavedPlan[]; page: number; pageSize: number; total: number }

export function fetchPlans(page = 1): Promise<PlanPage> {
  return requestJson(`/api/plans?page=${page}&pageSize=10`)
}

export function loadSavedPlan(plan: SavedPlan): Promise<SessionPayload> {
  return requestJson('/api/plans/load', { method: 'POST', body: JSON.stringify({ id: plan.id, runId: plan.runId }) })
}

export function renameSavedPlan(plan: SavedPlan, name: string): Promise<{ ok: true }> {
  return requestJson('/api/plans/rename', { method: 'POST', body: JSON.stringify({ id: plan.id, runId: plan.runId, name }) })
}

export function applyReviewed(decisions: Decision[], permanent = false, confirmation = ''): Promise<ApplyReviewedResult> {
  return requestJson<ApplyReviewedResult>('/api/apply-reviewed', {
    method: 'POST',
    body: JSON.stringify({ decisions, permanent, confirmation }),
  })
}

export function openInFolder(fileId: number): Promise<OpenInFolderResult> {
  return requestJson<OpenInFolderResult>('/api/open-in-folder', {
    method: 'POST',
    body: JSON.stringify({ fileId }),
  })
}

export function moveToFolder(fileId: number): Promise<MoveToFolderResult> {
  return requestJson<MoveToFolderResult>('/api/move-to-folder', {
    method: 'POST',
    body: JSON.stringify({ fileId }),
  })
}

type EditableSettings = Omit<DetectionSettings, 'rescanAvailable' | 'reportMinimumDuplicatePercent'>

export function updateSettings(settings: EditableSettings): Promise<SessionPayload> {
  return requestJson<SessionPayload>('/api/settings', {
    method: 'POST',
    body: JSON.stringify(settings),
  })
}

export function startRescan(settings: EditableSettings): Promise<RescanStatus> {
  return requestJson<RescanStatus>('/api/rescan', {
    method: 'POST',
    body: JSON.stringify(settings),
  })
}

export function fetchRescanStatus(): Promise<RescanStatus> {
  return requestJson<RescanStatus>('/api/rescan-status')
}

export function fetchApplyStatus(): Promise<RescanStatus> {
  return requestJson<RescanStatus>('/api/apply-status')
}
export function chooseScanFolder(): Promise<{ path: string | null }> {
  return requestJson('/api/choose-scan-folder', { method: 'POST', body: '{}' })
}
