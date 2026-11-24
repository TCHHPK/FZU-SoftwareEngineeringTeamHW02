<template>
  <div
    class="stat-card"
    :class="[`tone-${tone}`, { 'is-loading': loading }]"
    role="group"
    :aria-label="ariaLabel"
  >
    <div class="stat-label">{{ label }}</div>
    <div class="stat-value">
      <span class="num">{{ loading ? '—' : displayValue }}</span>
      <span v-if="unit && !loading" class="unit">{{ unit }}</span>
    </div>
    <div v-if="hint" class="stat-hint">{{ hint }}</div>
  </div>
</template>

<script setup>
/**
 * 单个统计卡（错题本首页四个数字用同一个组件，靠 tone 区分语义）。
 *
 * 只负责展示，不取数：值由调用方从 /wrong-questions 的 data 里算好传进来。
 * 颜色与圆角全部走 CSS 变量并带兜底，梁倩的令牌上线后自动跟随，不用改这里。
 */
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], default: 0 },
  unit: { type: String, default: '' },
  hint: { type: String, default: '' },
  /** primary | danger | warning | success | neutral */
  tone: { type: String, default: 'neutral' },
  loading: { type: Boolean, default: false }
})

const displayValue = computed(() => {
  const v = props.value
  if (typeof v === 'number') {
    return Number.isFinite(v) ? v.toLocaleString('zh-CN') : '—'
  }
  const s = v === null || v === undefined ? '' : String(v).trim()
  return s === '' ? '—' : s
})

const ariaLabel = computed(
  () => `${props.label}：${props.loading ? '加载中' : displayValue.value + (props.unit || '')}`
)
</script>

<style scoped>
.stat-card {
  --tone: var(--c-text-weak, #8390a3);
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 84px;
  padding: var(--space-3, 12px) var(--space-4, 16px);
  border: 1px solid var(--c-border, rgba(214, 227, 240, 0.9));
  border-radius: var(--radius-md, 10px);
  background: var(--c-surface, rgba(255, 255, 255, 0.72));
  box-shadow: var(--shadow-sm, 0 1px 2px rgba(36, 66, 105, 0.06));
  overflow: hidden;
}

/* 左侧色条：只做语义提示，不抢数字 */
.stat-card::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--tone);
}

.tone-primary { --tone: var(--c-primary, #409eff); }
.tone-danger { --tone: var(--el-color-danger, #f56c6c); }
.tone-warning { --tone: var(--el-color-warning, #e6a23c); }
.tone-success { --tone: var(--el-color-success, #67c23a); }
.tone-neutral { --tone: var(--c-text-weak, #8390a3); }

.stat-label {
  font-size: 12px;
  color: var(--c-text-weak, #8390a3);
  letter-spacing: 0.2px;
}

.stat-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
  line-height: 1.1;
}

.num {
  font-size: 26px;
  font-weight: 600;
  color: var(--c-text, #253957);
  font-variant-numeric: tabular-nums;
}

.unit {
  font-size: 12px;
  color: var(--c-text-weak, #8390a3);
}

.stat-hint {
  font-size: 11px;
  color: var(--c-text-weak, #9aa5b5);
}

.is-loading .num {
  color: var(--c-text-weak, #b8c2d0);
}

@media (max-width: 640px) {
  .stat-card { min-height: 74px; padding: 10px 12px; }
  .num { font-size: 22px; }
}
</style>
