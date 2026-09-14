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
  duplicateRanges: DuplicateRange[]
  videoUrl: string
  previewMode: 'direct' | 'transcoded'
}

export type DuplicateRange = {
  startSeconds: number
  endSeconds: number
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
  minimumDuration: number
  settings: DetectionSettings
  summary: {
    groupCount: number
    fileCount: number
    matchCount: number
    decidedCount: number
    totalBytes: number
    filteredShortFileCount: number
    filteredMatchCount: number
  }
  groups: DuplicateGroup[]
  initialDecisions: Decision[]
}

export type DetectionSettings = {
  minimumDuplicatePercent: number
  reportMinimumDuplicatePercent: number
  minimumDeleteCoverage: number
  minimumDuration: number
  sampleInterval: number
  minimumSegment: number
  hashDistance: number
  rescanAvailable: boolean
}

export type RescanStatus = {
  state: 'idle' | 'running' | 'completed' | 'failed'
  message?: string
}

export type SaveResult = {
  ok: true
  planPath: string
  actionCount: number
  unresolvedKeptCount: number
  reclaimBytes: number
}

export type ApplyFailure = {
  groupId: number
  path: string
  error: string
}

export type ApplyReviewedResult = {
  ok: boolean
  planPath: string
  resultPath: string
  quarantinePath: string | null
  reviewedSetCount: number
  appliedSetCount: number
  failedSetCount: number
  appliedFileCount: number
  failedFileCount: number
  reclaimBytes: number
  failures: ApplyFailure[]
  session: SessionPayload
}

export type Strategy =
  | 'delete-shallower'
  | 'delete-shorter-name'
  | 'delete-numbered-name'
  | 'delete-fully-covered'

export type FilterStatus = 'all' | 'unresolved' | 'decided'
