<template>
  <figure class="weak-chart">
    <figcaption class="chart-head">
      <span class="title">{{ title }}</span>
      <span class="sub">按错题次数排序</span>
    </figcaption>

    <p v-if="!rows.length" class="empty">{{ emptyText }}</p>

    <template v-else>
      <!-- 手写 SVG：不引图表库；viewBox 固定 600 宽，随容器等比缩放 -->
      <svg
        class="chart-svg"
        :viewBox="`0 0 ${W} ${H}`"
        role="img"
        :aria-label="ariaLabel"
        preserveAspectRatio="xMinYMin meet"
      >
        <g
          v-for="(w, i) in rows"
          :key="keyOf(w, i)"
          :transform="`translate(0 ${i * rowHeight})`"
        >
          <title>{{ tooltipOf(w) }}</title>

          <!-- 轨道：给出「满格」参照，没有它看不出条形比例 -->
          <rect
            :x="LABEL_W"
            y="4"
            :width="barMax"
            :height="rowHeight - 8"
            rx="4"
            class="track"
          />

          <text :x="0" :y="rowHeight / 2 + 4" class="label">
            {{ truncateLabel(w.knowledge_name, labelChars) }}
          </text>

          <rect
            :x="LABEL_W"
            y="4"
            :width="lengthOf(w)"
            :height="rowHeight - 8"
            rx="4"
            :class="['bar', `tone-${weaknessTone(w)}`]"
          />

          <text
            :x="LABEL_W + barMax + 8"
            :y="rowHeight / 2 + 4"
            class="value"
          >{{ countOf(w) }}</text>
        </g>
      </svg>

      <div v-if="showLegend" class="legend">
        <span v-for="l in legend" :key="l.text" class="legend-item">
          <i :class="['dot', `tone-${l.tone}`]" />{{ l.text }}
        </span>
      </div>
    </template>
  </figure>
</template>

<script setup>
/**
 * 薄弱知识点条形图（手写 SVG，不引任何图表库）。
 *
 * 数据直接用 GET /api/wrong-questions 返回的 weak_points，不需要等队列字段。
 * 长度按最大错题次数等比缩放；颜色跟随薄弱度（高 / 中 / 低）。
 * 用法：
 *   <WeaknessChart :weak-points="weakPoints" />
 */
import { computed } from 'vue'
import { barLength, topWeakPoints, truncateLabel, weaknessTone } from '@/utils/wrongStats'

const W = 600          // viewBox 宽度，实际显示宽度由容器决定
const LABEL_W = 132    // 左侧知识点名称占位
const VALUE_PAD = 40   // 右侧数字占位
const barMax = W - LABEL_W - VALUE_PAD

const props = defineProps({
  weakPoints: { type: Array, default: () => [] },
  title: { type: String, default: '薄弱知识点' },
  /** 最多显示几条，超出的不画（默认 6，页面高度可控） */
  maxRows: { type: Number, default: 6 },
  rowHeight: { type: Number, default: 24 },
  /** 左侧名称最多几个字，超出省略 */
  labelChars: { type: Number, default: 9 },
  showLegend: { type: Boolean, default: true },
  emptyText: { type: String, default: '暂无错题数据，先去做一次智能自测' }
})

const rows = computed(() => topWeakPoints(props.weakPoints, props.maxRows))
const maxCount = computed(() => Math.max(0, ...rows.value.map((w) => Number(w?.wrong_count) || 0)))
const H = computed(() => Math.max(props.rowHeight, rows.value.length * props.rowHeight + 6))

const legend = [
  { text: '高（≥3 次）', tone: 'danger' },
  { text: '中（2 次）', tone: 'warning' },
  { text: '低（1 次）', tone: 'info' }
]

function lengthOf(w) {
  return barLength(w?.wrong_count, maxCount.value, barMax)
}

function countOf(w) {
  const n = Number(w?.wrong_count) || 0
  return n > 0 ? n : '—'
}

function keyOf(w, i) {
  return `${w?.knowledge_name || 'unknown'}-${i}`
}

function tooltipOf(w) {
  const name = w?.knowledge_name || '未知知识点'
  const wrong = Number(w?.wrong_count) || 0
  const unmastered = Number(w?.unmastered_count)
  const mastered = Number(w?.mastered_count)
  const parts = [`错 ${wrong} 次`]
  if (Number.isFinite(unmastered)) parts.push(`未掌握 ${unmastered} 题`)
  if (Number.isFinite(mastered) && mastered > 0) parts.push(`已掌握 ${mastered} 题`)
  return `${name}：${parts.join('，')}`
}

const ariaLabel = computed(() => {
  if (!rows.value.length) return `${props.title}：暂无数据`
  const top = rows.value
    .slice(0, 3)
    .map((w) => `${w.knowledge_name} 错 ${Number(w?.wrong_count) || 0} 次`)
    .join('；')
  return `${props.title}，共 ${rows.value.length} 个知识点。前三位：${top}`
})
</script>

<style scoped>
.weak-chart {
  margin: 0;
  padding: var(--space-3, 12px) var(--space-4, 16px);
  border: 1px solid var(--c-border, rgba(214, 227, 240, 0.9));
  border-radius: var(--radius-md, 10px);
  background: var(--c-surface, rgba(255, 255, 255, 0.72));
  box-shadow: var(--shadow-sm, 0 1px 2px rgba(36, 66, 105, 0.06));
}

.chart-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
}

.chart-head .title {
  font-size: 13px;
  font-weight: 600;
  color: var(--c-text, #253957);
}

.chart-head .sub {
  font-size: 11px;
  color: var(--c-text-weak, #8390a3);
}

/* 宽 100% + 不写 height：SVG 按 viewBox 比例自适应高度 */
.chart-svg {
  display: block;
  width: 100%;
  max-width: 720px;   /* 宽屏下别把字号拉得比正文还大 */
  height: auto;
  overflow: visible;
}

.track {
  fill: var(--c-track, rgba(180, 196, 214, 0.18));
}

.label {
  font-size: 11px;
  fill: var(--c-text, #3a4a60);
}

.value {
  font-size: 10px;
  fill: var(--c-text-weak, #8390a3);
  font-variant-numeric: tabular-nums;
}

.bar.tone-danger { fill: var(--el-color-danger, #f56c6c); }
.bar.tone-warning { fill: var(--el-color-warning, #e6a23c); }
.bar.tone-info { fill: var(--c-primary, #409eff); }
.bar.tone-success { fill: var(--el-color-success, #67c23a); }

.empty {
  margin: 4px 0 2px;
  font-size: 12px;
  color: var(--c-text-weak, #8390a3);
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 8px;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--c-text-weak, #8390a3);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  display: inline-block;
}

.dot.tone-danger { background: var(--el-color-danger, #f56c6c); }
.dot.tone-warning { background: var(--el-color-warning, #e6a23c); }
.dot.tone-info { background: var(--c-primary, #409eff); }
</style>
