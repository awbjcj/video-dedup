import assert from 'node:assert/strict'
import test from 'node:test'

import { linkedGroupIds, updateLinkedGroupSelection } from './groupSelection.ts'
import type { DuplicateGroup } from '../types.ts'

function group(id: number, fileIds: number[]): DuplicateGroup {
  return {
    id,
    fileCount: fileIds.length,
    matchCount: 1,
    files: fileIds.map((fileId) => ({ id: fileId })),
  } as DuplicateGroup
}

const groups = [
  group(1, [10, 11]),
  group(2, [11, 12]),
  group(3, [12, 13]),
  group(4, [20, 21]),
]

test('linkedGroupIds follows shared videos transitively', () => {
  assert.deepEqual([...linkedGroupIds(groups, [1])].sort(), [1, 2, 3])
  assert.deepEqual([...linkedGroupIds(groups, [4])], [4])
})

test('updateLinkedGroupSelection marks and clears a linked set cluster together', () => {
  const selected = updateLinkedGroupSelection(groups, new Set([4]), [1], true)
  assert.deepEqual([...selected].sort(), [1, 2, 3, 4])

  const cleared = updateLinkedGroupSelection(groups, selected, [2], false)
  assert.deepEqual([...cleared], [4])
})
