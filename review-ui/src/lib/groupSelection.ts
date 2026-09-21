import type { DuplicateGroup } from '../types.ts'

/** Return every duplicate set connected to the seeds by one or more shared videos. */
export function linkedGroupIds(
  groups: DuplicateGroup[],
  seedGroupIds: Iterable<number>,
): Set<number> {
  const groupById = new Map(groups.map((group) => [group.id, group]))
  const groupIdsByFileId = new Map<number, number[]>()

  groups.forEach((group) => {
    group.files.forEach((file) => {
      const containingGroups = groupIdsByFileId.get(file.id) ?? []
      containingGroups.push(group.id)
      groupIdsByFileId.set(file.id, containingGroups)
    })
  })

  const linked = new Set<number>()
  const pending = [...seedGroupIds]
  while (pending.length) {
    const groupId = pending.pop()
    if (groupId === undefined || linked.has(groupId)) continue
    const group = groupById.get(groupId)
    if (!group) continue

    linked.add(groupId)
    group.files.forEach((file) => {
      groupIdsByFileId.get(file.id)?.forEach((relatedGroupId) => {
        if (!linked.has(relatedGroupId)) pending.push(relatedGroupId)
      })
    })
  }

  return linked
}

export function updateLinkedGroupSelection(
  groups: DuplicateGroup[],
  current: ReadonlySet<number>,
  seedGroupIds: Iterable<number>,
  selected: boolean,
): Set<number> {
  const next = new Set(current)
  linkedGroupIds(groups, seedGroupIds).forEach((groupId) => {
    if (selected) next.add(groupId)
    else next.delete(groupId)
  })
  return next
}
