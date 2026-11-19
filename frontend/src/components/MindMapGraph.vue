<template>
  <section class="mindmap-shell" aria-label="图形化思维导图">
    <div class="mindmap-toolbar">
      <div class="toolbar-title">
        <span class="toolbar-icon">◎</span>
        <div><strong>知识结构图</strong><small>拖动空白处平移 · 滚轮缩放 · 单击节点查看详情</small></div>
      </div>
      <div class="toolbar-actions">
        <el-button size="small" :disabled="!graph.nodes.length" @click="changeZoom(1.25)">放大 +</el-button>
        <el-button size="small" :disabled="!graph.nodes.length" @click="changeZoom(0.8)">缩小 −</el-button>
        <el-button size="small" :disabled="!graph.nodes.length" @click="fitView">适应画布</el-button>
        <el-button size="small" :disabled="!graph.nodes.length" @click="expandAll">全部展开</el-button>
        <span class="zoom-label">{{ Math.round(scale * 100) }}%</span>
      </div>
    </div>

    <div v-if="!normalized" class="mindmap-empty">
      <el-empty description="该任务暂无可显示的导图节点" />
    </div>
    <div v-else class="mindmap-body">
      <div ref="stageRef" class="mindmap-stage" :class="{ dragging: isDragging }">
        <svg
          class="mindmap-svg"
          xmlns="http://www.w3.org/2000/svg"
          :viewBox="`0 0 ${viewport.width} ${viewport.height}`"
          role="img"
          aria-label="可缩放、拖动和折叠的知识点树状思维导图"
          @wheel.prevent="onWheel"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="stopDrag"
          @pointercancel="stopDrag"
          @lostpointercapture="stopDrag"
        >
          <defs>
            <pattern id="u15-grid" width="24" height="24" patternUnits="userSpaceOnUse">
              <circle cx="2" cy="2" r="1" fill="#cad9e8" opacity=".6" />
            </pattern>
            <filter id="u15-shadow" x="-30%" y="-50%" width="170%" height="210%">
              <feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="#244269" flood-opacity=".11" />
            </filter>
          </defs>
          <rect :width="viewport.width" :height="viewport.height" fill="url(#u15-grid)" />
          <g :transform="`translate(${offset.x} ${offset.y}) scale(${scale})`">
            <path v-for="edge in graph.edges" :key="edge.id" :d="edge.path"
              fill="none" stroke="#9eb9d6" stroke-width="2" stroke-linecap="round" />
            <g v-for="node in graph.nodes" :key="node.id"
              class="mindmap-node" :class="{ selected: selectedId === node.id }"
              :transform="`translate(${node.x} ${node.y})`"
              tabindex="0" role="button"
              :aria-label="`选择节点：${node.name}`"
              @pointerdown.stop
              @click.stop="selectNode(node)"
              @keydown.enter.prevent="selectNode(node)"
              @keydown.space.prevent="selectNode(node)"
            >
              <rect x="0" y="-38" :width="node.width" :height="node.height" rx="13"
                :fill="selectedId === node.id ? '#e9f3ff' : '#fff'"
                :stroke="selectedId === node.id ? '#409eff' : '#d6e3f0'"
                :stroke-width="selectedId === node.id ? 2.5 : 1.25"
                filter="url(#u15-shadow)" />
              <rect x="0" y="-38" width="5" height="76" rx="2.5"
                :fill="node.id === normalized.id ? '#5274e7' : '#6db6af'" />
              <text x="16" y="-12" fill="#253957" font-weight="650" font-size="14">
                {{ clipText(node.name, 12) }}
              </text>
              <text x="16" y="12" fill="#8390a3" font-size="11">
                {{ clipText(node.summary || (node.hasChildren ? '点击查看分支' : '点击查看详情'), 16) }}
              </text>
              <g v-if="node.hasChildren" class="collapse-icon" role="button"
                 :aria-label="node.collapsed ? '展开分支' : '折叠分支'"
                 @pointerdown.stop @click.stop="toggleNode(node)">
                <circle :cx="node.width - 13" cy="0" r="13" fill="#f1f6ff" stroke="#bdd3ea" />
                <text :x="node.width - 13" y="5" text-anchor="middle" font-size="17"
                  fill="#3f6ba1">{{ node.collapsed ? '+' : '−' }}</text>
              </g>
            </g>
          </g>
        </svg>
        <span class="canvas-hint">{{ graph.nodes.length }} 个可见节点</span>
      </div>

      <aside class="mindmap-detail" aria-live="polite">
        <div class="detail-eyebrow">当前节点</div>
        <h3>{{ activeNode?.name || '请选择节点' }}</h3>
        <template v-if="activeNode">
          <p class="detail-summary">{{ activeNode.summary || '该节点暂未提供摘要。' }}</p>
          <div class="detail-divider"></div>
          <div class="detail-eyebrow">原文出处</div>
          <p v-if="activeNode.evidence_page != null" class="detail-evidence">
            <el-tag type="info">第 {{ activeNode.evidence_page }} 页</el-tag>
          </p>
          <p v-else-if="activeNode.evidence_slide != null" class="detail-evidence">
            <el-tag type="info">第 {{ activeNode.evidence_slide }} 张幻灯片</el-tag>
          </p>
          <p v-else class="detail-muted">未提供页码或幻灯片序号</p>
          <p v-if="activeNode.evidence_chunk_key" class="detail-key">
            证据编号：{{ activeNode.evidence_chunk_key }}
          </p>
          <p v-else class="detail-muted">未提供证据编号</p>
          <p v-if="activeNode.children.length" class="detail-muted">
            包含 {{ activeNode.children.length }} 个直接子节点，单击节点右侧的 + / − 可折叠分支。
          </p>
        </template>
      </aside>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { layoutMindmap, normalizeMindmap } from '@/utils/mindmap'

const props = defineProps({
  tree: { type: [Object, Array], default: null }
})
const emit = defineEmits(['select'])
const normalized = computed(() => normalizeMindmap(props.tree))
const collapsedIds = ref(new Set())
const selectedId = ref(null)
const graph = computed(() => layoutMindmap(normalized.value, collapsedIds.value))
const activeNode = computed(() => graph.value.nodes.find((node) => node.id === selectedId.value) || null)
const stageRef = ref(null)
const viewport = ref({ width: 800, height: 580 })
const scale = ref(1)
const offset = ref({ x: 0, y: 0 })
const isDragging = ref(false)
let observer
let dragPoint = null

function clipText(text, max) {
  const chars = Array.from(String(text || ''))
  return chars.length > max ? `${chars.slice(0, max - 1).join('')}…` : chars.join('')
}
function selectNode(node) {
  selectedId.value = node.id
  emit('select', node)
}
function toggleNode(node) {
  const updated = new Set(collapsedIds.value)
  if (updated.has(node.id)) updated.delete(node.id)
  else updated.add(node.id)
  collapsedIds.value = updated
  // 隐藏的子节点不能保留为当前选中项。
  if (!graph.value.nodes.some((current) => current.id === selectedId.value)) {
    selectNode(node)
  }
}
function expandAll() {
  collapsedIds.value = new Set()
  nextTick(fitView)
}
function fitView() {
  if (!graph.value.nodes.length) return
  const { width, height } = viewport.value
  const factor = Math.min((width - 48) / graph.value.width, (height - 48) / graph.value.height)
  scale.value = Math.max(0.2, Math.min(1.6, factor))
  offset.value = {
    x: (width - graph.value.width * scale.value) / 2,
    y: (height - graph.value.height * scale.value) / 2
  }
}
function zoomAt(factor, x, y) {
  const newScale = Math.max(0.2, Math.min(3, scale.value * factor))
  const ratio = newScale / scale.value
  offset.value = { x: x - (x - offset.value.x) * ratio, y: y - (y - offset.value.y) * ratio }
  scale.value = newScale
}
function changeZoom(factor) {
  zoomAt(factor, viewport.value.width / 2, viewport.value.height / 2)
}
function onWheel(event) {
  const rect = stageRef.value?.getBoundingClientRect()
  if (!rect) return
  zoomAt(Math.exp(-event.deltaY * 0.001), event.clientX - rect.left, event.clientY - rect.top)
}
function onPointerDown(event) {
  if (event.button !== 0) return
  isDragging.value = true
  dragPoint = { pointerId: event.pointerId, x: event.clientX, y: event.clientY }
  event.currentTarget.setPointerCapture(event.pointerId)
}
function onPointerMove(event) {
  if (!dragPoint || event.pointerId !== dragPoint.pointerId) return
  offset.value = {
    x: offset.value.x + event.clientX - dragPoint.x,
    y: offset.value.y + event.clientY - dragPoint.y
  }
  dragPoint.x = event.clientX
  dragPoint.y = event.clientY
}
function stopDrag() {
  isDragging.value = false
  dragPoint = null
}
function onResize() {
  if (!stageRef.value) return
  viewport.value = {
    width: Math.max(320, stageRef.value.clientWidth),
    height: Math.max(300, stageRef.value.clientHeight)
  }
  fitView()
}
watch(normalized, (root) => {
  collapsedIds.value = new Set()
  selectedId.value = root?.id ?? null
  if (root) emit('select', root)
  nextTick(fitView)
}, { immediate: true })
onMounted(() => {
  observer = new ResizeObserver(onResize)
  if (stageRef.value) observer.observe(stageRef.value)
  nextTick(onResize)
})
onUnmounted(() => observer?.disconnect())
</script>

<style scoped>
.mindmap-shell { width: 100%; border: 1px solid #e0e8f2; border-radius: 16px; background: #fff; overflow: hidden; }
.mindmap-toolbar { padding: 14px 18px; display: flex; gap: 14px; flex-wrap: wrap; align-items: center; justify-content: space-between; border-bottom: 1px solid #e6edf5; }
.toolbar-title { display: flex; align-items: center; gap: 12px; }
.toolbar-icon { width: 36px; height: 36px; border-radius: 11px; display: flex; align-items: center; justify-content: center; background: #ecf3ff; color: #4373cc; font-size: 24px; }
.toolbar-title strong { display: block; font-size: 15px; color: #26374a; }
.toolbar-title small { display: block; margin-top: 3px; font-size: 11px; color: #8a96a8; }
.toolbar-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.toolbar-actions .el-button { margin-left: 0; }
.zoom-label { width: 48px; text-align: right; color: #6d7c90; font-size: 12px; }
.mindmap-body { display: grid; grid-template-columns: minmax(0, 1fr) 244px; }
.mindmap-stage { position: relative; min-width: 0; height: 585px; cursor: grab; touch-action: none; background: linear-gradient(150deg, #f9fcff, #f2f7ff); }
.mindmap-stage.dragging { cursor: grabbing; }
.mindmap-svg { width: 100%; height: 100%; display: block; user-select: none; }
.mindmap-node { cursor: pointer; outline: none; }
.mindmap-node:focus-visible rect:first-child { stroke: #287fdc; stroke-width: 3; }
.collapse-icon { cursor: pointer; }
.canvas-hint { position: absolute; left: 14px; bottom: 12px; font-size: 11px; color: #95a6b8; pointer-events: none; }
.mindmap-detail { padding: 24px 20px; border-left: 1px solid #e2eaf4; background: #fcfdff; overflow-wrap: anywhere; }
.detail-eyebrow { color: #8494aa; font-size: 12px; font-weight: 600; letter-spacing: .06em; }
.mindmap-detail h3 { font-size: 18px; line-height: 1.5; color: #23354d; margin: 10px 0 16px; }
.detail-summary { color: #526275; font-size: 13px; line-height: 1.9; white-space: pre-wrap; }
.detail-divider { border-top: 1px solid #e6edf4; margin: 23px 0; }
.detail-evidence { margin: 12px 0; }
.detail-key { font-size: 12px; line-height: 1.7; color: #667c97; word-break: break-all; }
.detail-muted { font-size: 12px; line-height: 1.7; color: #99a5b4; }
.mindmap-empty { padding: 48px 0; }
@media (max-width: 950px) { .mindmap-body { grid-template-columns: 1fr; } .mindmap-stage { height: 450px; } .mindmap-detail { border-left: 0; border-top: 1px solid #e2eaf4; } }
</style>
