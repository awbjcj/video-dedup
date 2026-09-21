import type { Decision, DuplicateGroup, FilterStatus } from '@/types'

export function filterReviewGroups(
  groups: DuplicateGroup[],
  decisions: Map<number, Decision>,
  filter: FilterStatus,
  query: string,
): DuplicateGroup[] {
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
}
