import test from 'node:test'
import assert from 'node:assert/strict'
import { layoutMindmap, normalizeMindmap, previewTreeFromResult } from '../src/utils/mindmap.js'

test('empty response never creates fake knowledge nodes', () => {
  assert.equal(normalizeMindmap(null), null)
  assert.equal(normalizeMindmap({ nodes: [] }), null)
})

test('nested backend tree preserves page, evidence and hierarchical nodes', () => {
  const root = normalizeMindmap({ tree: {
    node_id: 1, name: '软件工程', children: [
      { node_id: 2, name: '设计原则', evidence_page: 12,
        evidence_chunk_key: 'd2-p12-c1', summary: '定义', children: [] }
    ]
  } })
  assert.equal(root.children.length, 1)
  assert.equal(root.children[0].evidence_page, 12)
  assert.equal(root.children[0].evidence_chunk_key, 'd2-p12-c1')
  assert.equal(layoutMindmap(root).nodes.length, 2)
  assert.equal(layoutMindmap(root, new Set(['1'])).nodes.length, 1)
})

test('flat adjacency list sorted by seq becomes a nested tree', () => {
  const root = normalizeMindmap({nodes: [
    {node_id: 3, parent_id: 1, seq: 2, name: 'B'},
    {node_id: 1, parent_id: null, seq: 0, name: 'ROOT'},
    {node_id: 2, parent_id: 1, seq: 1, name: 'A'}
  ]})
  assert.deepEqual(root.children.map((v) => v.name), ['A', 'B'])
  assert.equal(layoutMindmap(root).edges.length, 2)
})

test('preview uses real note chapters and source page, not synthetic content', () => {
  const tree = previewTreeFromResult({ course_name: '软件工程', items: [
    { name: '依赖倒置', definition: '依赖抽象', evidence: [
      { chapter_title: '设计原则', page_num: 23, chunk_key: 'd1-p23-c2' }
    ] }
  ] })
  assert.equal(tree.children[0].name, '设计原则')
  assert.equal(tree.children[0].children[0].evidence_page, 23)
  assert.equal(tree.children[0].children[0].evidence_chunk_key, 'd1-p23-c2')
  assert.equal(previewTreeFromResult({ items: [] }), null)
  const slides = previewTreeFromResult({ items: [
    { name: 'PPT 测试', evidence: [{slide_index: 4, chunk_key: 'd1-s4-c2'}] }
  ] })
  assert.equal(normalizeMindmap(slides).children[0].children[0].evidence_slide, 4)
})
