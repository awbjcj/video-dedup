import assert from 'node:assert/strict'
import test from 'node:test'
import { removalFiles, updateDecisions } from './reviewDecisions.ts'
import type { Decision, DuplicateGroup } from '../types.ts'

const groups = [
  { id: 1, fileCount: 2, matchCount: 1, files: [{ id: 10, sizeBytes: 100 }, { id: 11, sizeBytes: 200 }] },
  { id: 2, fileCount: 2, matchCount: 1, files: [{ id: 10, sizeBytes: 100 }, { id: 12, sizeBytes: 300 }] },
  { id: 3, fileCount: 2, matchCount: 1, files: [{ id: 20, sizeBytes: 400 }, { id: 21, sizeBytes: 500 }] },
] as DuplicateGroup[]
const choice = (groupId: number, keeperIds: number[]): Decision => ({ groupId, keeperIds, method: 'web-manual' })

test('a shared removal has one file identity without marking other sets reviewed', () => {
  const decisions = updateDecisions(groups, new Map(), [choice(1, [11])])
  assert.deepEqual([...decisions.keys()], [1])
  assert.deepEqual([...removalFiles(groups, decisions).keys()], [10])
})

test('new removal updates previously reviewed sets and counts shared bytes once', () => {
  const original = new Map([[2, choice(2, [10, 12])], [3, choice(3, [20])]])
  const decisions = updateDecisions(groups, original, [choice(1, [11])])
  assert.deepEqual(decisions.get(2)?.keeperIds, [12])
  assert.deepEqual(decisions.get(3)?.keeperIds, [20])
  assert.deepEqual(original.get(2)?.keeperIds, [10, 12])
  const files = removalFiles(groups, decisions)
  assert.equal(files.size, 2)
  assert.equal([...files.values()].reduce((sum, file) => sum + file.sizeBytes, 0), 600)
})

test('keeping a shared file again updates every reviewed occurrence', () => {
  const decisions = updateDecisions(groups, new Map([[1, choice(1, [11])]]), [choice(2, [10, 12])])
  assert.deepEqual(decisions.get(1)?.keeperIds, [10, 11])
  assert.equal(removalFiles(groups, decisions).size, 0)
})

test('conflicting legacy saved choices display the same safe keep decision everywhere', () => {
  const decisions = new Map([[1, choice(1, [11])], [2, choice(2, [10, 12])]])
  assert.equal(removalFiles(groups, decisions).size, 0)
})

test('global synchronization can leave a reviewed set covered entirely by other sets', () => {
  const decisions = updateDecisions(groups, new Map([[2, choice(2, [10])]]), [choice(1, [11])])
  assert.deepEqual(decisions.get(2)?.keeperIds, [])
  assert.deepEqual([...removalFiles(groups, decisions).keys()].sort(), [10, 12])
})
