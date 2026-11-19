/**
 * U15 导图树契约适配：支持后端返回 {tree: root}、{nodes: [...]}
 * 和直接返回嵌套节点。非渲染代码，可用 node --test 独立验证。
 * 只从服务端数据构树；不自动生成或伪造知识内容。
 */
function unwrap(payload) {
  if (!payload) return null
  const value = payload.data ?? payload
  if (Array.isArray(value)) return value
  if (value && typeof value === 'object') {
    if ('tree' in value) return value.tree
    if ('root' in value) return value.root
    if ('nodes' in value) return value.nodes
  }
  return value
}

function isNode(value) {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value) &&
    (value.name || value.title || value.label))
}

function nodeLabel(node) {
  return String(node.name || node.title || node.label || '').trim()
}

function childrenOf(node) {
  return node.children ?? node.nodes ?? node.branches ?? []
}

function toNode(raw, fallbackId, visited, depth = 0) {
  if (!isNode(raw) || depth > 50 || visited.has(raw)) return null
  visited.add(raw)
  const childList = Array.isArray(childrenOf(raw)) ? childrenOf(raw) : []
  const children = childList.map((child, index) =>
    toNode(child, `${fallbackId}.${index + 1}`, visited, depth + 1)).filter(Boolean)
  visited.delete(raw)
  const evidence = raw.evidence && !Array.isArray(raw.evidence) ? raw.evidence :
    Array.isArray(raw.evidence) ? raw.evidence[0] : null
  return {
    id: String(raw.node_id ?? raw.id ?? raw.key ?? fallbackId),
    name: nodeLabel(raw),
    summary: String(raw.summary ?? raw.description ?? raw.definition ?? ''),
    evidence_page: raw.evidence_page ?? raw.page_num ?? evidence?.page_num ?? null,
    evidence_slide: raw.evidence_slide ?? raw.slide_index ?? evidence?.slide_index ?? null,
    evidence_chunk_key: String(raw.evidence_chunk_key ?? evidence?.chunk_key ?? ''),
    children
  }
}

/** 扁平邻接表 => 树；按 seq 排序；根节点 parent_id 必须为空或找不到父节点。 */
function flatToTrees(raw) {
  const entries = raw.filter(isNode).map((node, index) => ({
    ...node, children: [], _position: index
  }))
  const byId = new Map(entries.map((node) => [String(node.node_id ?? node.id), node]))
  const roots = []
  for (const node of entries) {
    const ownId = String(node.node_id ?? node.id)
    const parentId = node.parent_id
    const parent = parentId === undefined || parentId === null ? null : byId.get(String(parentId))
    // 保护脏数据：避免自引用或父子循环导致递归不终止。
    let cursor = parent
    let cyclic = false
    const visited = new Set([ownId])
    while (cursor) {
      const key = String(cursor.node_id ?? cursor.id)
      if (visited.has(key)) { cyclic = true; break }
      visited.add(key)
      const next = cursor.parent_id
      cursor = next === undefined || next === null ? null : byId.get(String(next))
    }
    if (parent && !cyclic) parent.children.push(node)
    else roots.push(node)
  }
  function sortBranch(items) {
    items.sort((a, b) => Number(a.seq ?? a._position) - Number(b.seq ?? b._position))
    for (const item of items) sortBranch(item.children)
  }
  sortBranch(roots)
  return roots
}

/** 统一为一个根节点，空数据返回 null。 */
export function normalizeMindmap(payload) {
  const source = unwrap(payload)
  if (!source) return null
  let list
  if (Array.isArray(source)) {
    list = source.some((n) => n && Object.hasOwn(n, 'parent_id'))
      ? flatToTrees(source) : source
  } else if (isNode(source)) {
    list = [source]
  } else {
    return null
  }
  const visited = new WeakSet()
  const roots = list.map((item, i) => toNode(item, `root-${i + 1}`, visited)).filter(Boolean)
  if (!roots.length) return null
  if (roots.length === 1) return roots[0]
  return {
    id: '__virtual_root__',
    name: String(payload?.course_name ?? payload?.data?.course_name ?? '课程思维导图'),
    summary: '', evidence_page: null, evidence_slide: null, evidence_chunk_key: '', children: roots
  }
}

/** 依据可见节点生成 SVG 布局；collapsed 为折叠节点的 id 集合。 */
export function layoutMindmap(root, collapsed = new Set()) {
  if (!root) return { nodes: [], edges: [], width: 0, height: 0 }
  const nodes = []
  const edges = []
  const positions = new Map()
  const column = 258
  const row = 112
  const nodeWidth = 208
  const nodeHeight = 76
  let leafIndex = 0
  let maxDepth = 0
  function place(node, depth, parentId = null) {
    maxDepth = Math.max(maxDepth, depth)
    const children = collapsed.has(node.id) ? [] : node.children || []
    let y
    if (!children.length) {
      y = 82 + leafIndex * row
      leafIndex += 1
    } else {
      const positionsY = children.map((child) => place(child, depth + 1, node.id))
      y = (positionsY[0] + positionsY[positionsY.length - 1]) / 2
    }
    const x = 35 + depth * column
    const placed = {
      ...node, x, y, width: nodeWidth, height: nodeHeight,
      hasChildren: Boolean(node.children?.length), collapsed: collapsed.has(node.id)
    }
    nodes.push(placed)
    positions.set(node.id, placed)
    if (parentId !== null) edges.push({ parentId, childId: node.id })
    return y
  }
  place(root, 0)
  return {
    nodes: nodes.sort((a, b) => a.x - b.x || a.y - b.y),
    edges: edges.map(({ parentId, childId }) => {
      const parent = positions.get(parentId)
      const child = positions.get(childId)
      const sx = parent.x + nodeWidth
      const tx = child.x
      const sy = parent.y
      const ty = child.y
      const delta = Math.max(35, (tx - sx) * 0.5)
      return { id: `${parentId}=>${childId}`,
        path: `M ${sx} ${sy} C ${sx + delta} ${sy}, ${tx - delta} ${ty}, ${tx} ${ty}` }
    }),
    width: 35 + maxDepth * column + nodeWidth + 45,
    height: Math.max(250, 82 + Math.max(0, leafIndex - 1) * row + 90)
  }
}

/** 源于 ResultView 已有真实知识点：后端未实现前只作为未持久化预览。 */
export function previewTreeFromResult(result) {
  const items = Array.isArray(result?.items) ? result.items : []
  if (!items.length) return null
  const chapters = new Map()
  items.forEach((item, index) => {
    const evidence = Array.isArray(item.evidence) ? item.evidence[0] : null
    const chapterTitle = evidence?.chapter_title || '未标注章节'
    if (!chapters.has(chapterTitle)) chapters.set(chapterTitle, [])
    chapters.get(chapterTitle).push({
      id: `preview-item-${index}`,
      name: item.name || '未命名知识点',
      summary: item.definition || '',
      evidence_page: evidence?.page_num ?? null,
      evidence_slide: evidence?.slide_index ?? null,
      evidence_chunk_key: evidence?.chunk_key || '', children: []
    })
  })
  return {
    id: 'preview-course', name: result.course_name || '课程笔记', summary: '基于已整理的章节与知识点',
    children: [...chapters.entries()].map(([name, children], i) => ({
      id: `preview-chapter-${i}`, name, summary: `包含 ${children.length} 个知识点`, children
    }))
  }
}
