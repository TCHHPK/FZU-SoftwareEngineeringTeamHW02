import test from 'node:test'
import assert from 'node:assert/strict'
import {
  MASTERY_THRESHOLD,
  barLength,
  summarizeWrongBook,
  topWeakPoints,
  truncateLabel,
  weaknessOf,
  weaknessTone
} from '../src/utils/wrongStats.js'

test('空数据不报错，四个统计值都给 0', () => {
  for (const input of [null, undefined, {}, { items: [] }]) {
    assert.deepEqual(summarizeWrongBook(input), {
      total: 0,
      mastered: 0,
      unmastered: 0,
      weakCount: 0,
      rate: 0
    })
  }
})

test('统计卡口径：mastered 取 items，未掌握按 total 差值，掌握率取整', () => {
  const data = {
    total: 7,
    items: [
      { wrong_id: 1, mastered: true },
      { wrong_id: 2, mastered: false },
      { wrong_id: 3, mastered: false }
    ],
    weak_points: [
      { knowledge_name: '开闭原则', wrong_count: 3, weakness: '高' },
      { knowledge_name: '依赖倒置', wrong_count: 1, weakness: '已掌握' }
    ]
  }
  const s = summarizeWrongBook(data)
  assert.equal(s.total, 7)
  assert.equal(s.mastered, 1)
  assert.equal(s.unmastered, 6)
  assert.equal(s.weakCount, 1, '已掌握的知识点不算薄弱')
  assert.equal(s.rate, 14)
})

test('total 缺失时退回 items.length，不会出现 NaN', () => {
  const s = summarizeWrongBook({ items: [{ mastered: true }, { mastered: true }] })
  assert.equal(s.total, 2)
  assert.equal(s.mastered, 2)
  assert.equal(s.unmastered, 0)
  assert.equal(s.rate, 100)
})

test('薄弱度：后端给了就用，没给按错题次数推', () => {
  assert.equal(weaknessOf({ wrong_count: 5, weakness: '中' }), '中')
  assert.equal(weaknessOf({ wrong_count: 3 }), '高')
  assert.equal(weaknessOf({ wrong_count: 2 }), '中')
  assert.equal(weaknessOf({ wrong_count: 1 }), '低')
  assert.equal(weaknessOf({ wrong_count: 9, mastered: true }), '已掌握')
  assert.equal(weaknessTone({ wrong_count: 3 }), 'danger')
  assert.equal(weaknessTone({ wrong_count: 2 }), 'warning')
  assert.equal(weaknessTone({ wrong_count: 1 }), 'info')
  assert.equal(weaknessTone({ wrong_count: 3, weakness: '已掌握' }), 'success')
})

test('排行：错题多在前，已掌握沉底，同分按名称排，条数受 limit 限制', () => {
  const points = [
    { knowledge_name: 'B 原则', wrong_count: 2 },
    { knowledge_name: 'A 原则', wrong_count: 2 },
    { knowledge_name: 'C 原则', wrong_count: 5 },
    { knowledge_name: '已掌握项', wrong_count: 9, weakness: '已掌握' }
  ]
  const top = topWeakPoints(points, 3)
  assert.deepEqual(top.map((w) => w.knowledge_name), ['C 原则', 'A 原则', 'B 原则'])
  assert.equal(top.length, 3)
  assert.equal(topWeakPoints(points, 0).length, 0)
  assert.equal(topWeakPoints(null).length, 0)
  assert.equal(topWeakPoints(points, 10).length, 4, '不足 limit 时返回全部')
})

test('排行不改动传入数组（组件是纯展示，不能悄悄改 props）', () => {
  const points = [{ knowledge_name: 'x', wrong_count: 1 }, { knowledge_name: 'y', wrong_count: 3 }]
  const snapshot = points.map((p) => p.knowledge_name)
  topWeakPoints(points, 2)
  assert.deepEqual(points.map((p) => p.knowledge_name), snapshot)
})

test('条形长度：等比缩放，有值至少 6px，除零安全', () => {
  assert.equal(barLength(5, 5, 100), 100)
  assert.equal(barLength(1, 5, 100), 20)
  assert.equal(barLength(5, 0, 100), 0)
  assert.equal(barLength(0, 5, 100), 0)
  assert.equal(barLength(1, 100, 100), 6, '极小值也要看得见')
  assert.equal(barLength('3', '6', '120'), 60)
})

test('长名称截断按码点切，不切坏中文与 emoji', () => {
  assert.equal(truncateLabel('开闭原则', 8), '开闭原则')
  assert.equal(truncateLabel('构件与对象的区别与联系', 6), '构件与对象…')
  assert.equal(Array.from(truncateLabel('软🧑‍💻件工程', 4)).length <= 4, true)
  assert.equal(truncateLabel('', 4), '')
  assert.equal(truncateLabel(null, 4), '')
})

test('掌握阈值与后端约定一致（连对 2 次）', () => {
  assert.equal(MASTERY_THRESHOLD, 2)
})
