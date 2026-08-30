import type { Decision, SaveResult, SessionPayload, Strategy } from '@/types'

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

export function savePlan(decisions: Decision[]): Promise<SaveResult> {
  return requestJson<SaveResult>('/api/plan', {
    method: 'POST',
    body: JSON.stringify({ decisions }),
  })
}
