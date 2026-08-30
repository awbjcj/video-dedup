export type VideoFile = {
  id: number
  name: string
  path: string
  folder: string
  sizeBytes: number
  durationSeconds: number
  width: number
  height: number
  codec: string
  coveredPercent: number
  videoUrl: string
  previewMode: 'direct' | 'transcoded'
}

export type DuplicateGroup = {
  id: number
  fileCount: number
  matchCount: number
  files: VideoFile[]
}

export type Decision = {
  groupId: number
  keeperIds: number[]
  method: string
}

export type SessionPayload = {
  reportPath: string
  planPath: string
  minimumCoverage: number
  summary: {
    groupCount: number
    fileCount: number
    matchCount: number
    decidedCount: number
    totalBytes: number
  }
  groups: DuplicateGroup[]
  initialDecisions: Decision[]
}

export type SaveResult = {
  ok: true
  planPath: string
  actionCount: number
  unresolvedKeptCount: number
  reclaimBytes: number
}

export type Strategy =
  | 'delete-shallower'
  | 'delete-shorter-name'
  | 'delete-numbered-name'
  | 'delete-fully-covered'

export type FilterStatus = 'all' | 'unresolved' | 'decided'
