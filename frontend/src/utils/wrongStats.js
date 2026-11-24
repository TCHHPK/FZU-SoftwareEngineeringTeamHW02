/**
 * 错题本统计的纯计算逻辑。
 *
 * 为什么要单独抽出来：
 *   组件只负责画，数字怎么算集中在这里，可以用 node --test 直接跑，
 *   不依赖浏览器，也不会因为页面改版而丢掉口径。
 *
 * 数据来源：GET /api/wrong-questions 的 data
 *   { total, items: WrongQuestionOut[], weak_points: WeakPoint[] }
 *   weak_points 每项：knowledge_name / wrong_count / unmastered_count /
 *                    mastered_count / weakness（高 | 中 | 低 | 已掌握）
 */

/** 掌握阈值：与后端 wrong_book.py 的 mastery_threshold 保持一致 */
export const MASTERY_THRESHOLD = 2

/** 薄弱度 → 视觉基调，供组件映射颜色 */
const TONE_MAP = {
  高: 'danger',
  中: 'warning',
  低: 'info',
  已掌握: 'success'
}

/**
 * 汇总错题本首页的四张统计卡。
 * @param {{total?:number, items?:Array, weak_points?:Array}|null} data 接口 data
 * @returns {{total:number, mastered:number, unmastered:number, weakCount:number, rate:number}}
 */
export function summarizeWrongBook(data) {
  const items = Array.isArray(data?.items) ? data.items : []
  const weakPoints = Array.isArray(data?.weak_points) ? data.weak_points : []

  const total = Number.isFinite(data?.total) ? Number(data.total) : items.length
  const mastered = items.filter((it) => it?.mastered === true).length
  // 接口一次性返回全部错题，items 与 total 应对齐；若列表被截断，未掌握数按差值兜底
  const unmastered = Math.max(total - mastered, 0)
  const weakCount = weakPoints.filter((w) => weaknessOf(w) !== '已掌握').length
  const rate = total > 0 ? Math.round((mastered / total) * 100) : 0

  return { total, mastered, unmastered, weakCount, rate }
}

/**
 * 取薄弱度标签；后端没给时按错题次数推。
 * 口径：错 ≥3 次为高、2 次为中、1 次为低；已掌握的单独标。
 */
export function weaknessOf(point) {
  const given = point?.weakness
  if (given === '高' || given === '中' || given === '低' || given === '已掌握') return given
  if (point?.mastered === true) return '已掌握'
  const n = Number(point?.wrong_count) || 0
  if (n >= 3) return '高'
  if (n === 2) return '中'
  return n >= 1 ? '低' : '低'
}

/** 薄弱度 → 基调（danger / warning / info / success） */
export function weaknessTone(point) {
  return TONE_MAP[weaknessOf(point)] || 'info'
}

/**
 * 取前 N 个薄弱知识点：错题次数降序，次数相同按名称升序（保证渲染稳定）。
 * 已掌握的排最后，避免长期占位。
 */
export function topWeakPoints(weakPoints, limit = 6) {
  const list = Array.isArray(weakPoints) ? weakPoints.slice() : []
  const n = Math.max(0, Number(limit) || 0)
  return list
    .sort((a, b) => {
      const am = weaknessOf(a) === '已掌握' ? 1 : 0
      const bm = weaknessOf(b) === '已掌握' ? 1 : 0
      if (am !== bm) return am - bm
      const d = (Number(b?.wrong_count) || 0) - (Number(a?.wrong_count) || 0)
      if (d !== 0) return d
      return String(a?.knowledge_name || '').localeCompare(String(b?.knowledge_name || ''), 'zh')
    })
    .slice(0, n)
}

/**
 * 条形长度：按最大值等比缩放到 maxWidth，最小 6（有错题就看得见）。
 * maxWidth 或 max 为 0 时返回 0，避免除零。
 */
export function barLength(count, max, maxWidth) {
  const c = Number(count) || 0
  const m = Number(max) || 0
  const w = Number(maxWidth) || 0
  if (c <= 0 || m <= 0 || w <= 0) return 0
  return Math.max(6, Math.round((c / m) * w))
}

/**
 * 截断长知识点名：按 Unicode 码点切，避免把 emoji/生僻字切坏。
 * 超出时补一个省略号，总长度不超过 maxChars。
 */
export function truncateLabel(name, maxChars = 8) {
  const chars = Array.from(String(name ?? ''))
  const max = Math.max(1, Number(maxChars) || 1)
  if (chars.length <= max) return chars.join('')
  return chars.slice(0, Math.max(1, max - 1)).join('') + '…'
}
