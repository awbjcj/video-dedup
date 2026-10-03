import type { Decision, DuplicateGroup, VideoFile } from '../types.ts'

export function updateDecisions(
  groups: DuplicateGroup[],
  current: ReadonlyMap<number, Decision>,
  updates: Decision[],
): Map<number, Decision> {
  const next = new Map(current)
  const groupById = new Map(groups.map((group) => [group.id, group]))
  for (const update of updates) {
    const group = groupById.get(update.groupId)
    if (!group) continue
    const changedFiles = new Set(group.files.map((file) => file.id))
    const keepers = new Set(update.keeperIds)
    next.set(update.groupId, update)
    for (const [groupId, decision] of next) {
      if (groupId === update.groupId) continue
      const other = groupById.get(groupId)
      if (!other?.files.some((file) => changedFiles.has(file.id))) continue
      const previousKeepers = new Set(decision.keeperIds)
      next.set(groupId, {
        ...decision,
        keeperIds: other.files.filter((file) => changedFiles.has(file.id)
          ? keepers.has(file.id) : previousKeepers.has(file.id)).map((file) => file.id),
      })
    }
  }
  return next
}

export function removalFiles(
  groups: DuplicateGroup[],
  decisions: ReadonlyMap<number, Decision>,
): Map<number, VideoFile> {
  const keepers = new Set([...decisions.values()].flatMap((decision) => decision.keeperIds))
  const files = new Map<number, VideoFile>()
  for (const group of groups) {
    const decision = decisions.get(group.id)
    if (!decision) continue
    for (const file of group.files) {
      if (!decision.keeperIds.includes(file.id) && !keepers.has(file.id)) files.set(file.id, file)
    }
  }
  return files
}
