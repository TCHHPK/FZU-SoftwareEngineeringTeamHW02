# 错题页统计区 · 接入说明（吴雅晴 → 陈佳慧）

> 交付日 2026-11-24 ｜ 截止 11.29 22:00 ｜ 归属：`components/StatsCard`、`components/WeaknessChart`
> 不改 `WrongBookView.vue` 与 `style.css`，只在你的页面里插一段，删掉即可回滚。

## 一、这次交了什么

| 文件 | 作用 |
| --- | --- |
| `src/components/StatsCard.vue` | 单个统计卡（四个数字共用，靠 `tone` 区分语义色） |
| `src/components/WeaknessChart.vue` | 薄弱知识点条形图，**手写 SVG**，未引入任何图表库 |
| `src/utils/wrongStats.js` | 纯计算：四项统计口径、排序取前 N、条形长度、名称截断 |
| `tests/wrongStats.test.mjs` | 9 项单测，`node --test` 直接跑，不需要 npm install |
| `preview-wrongbook-stats.html` | 静态预览，双击就能看效果（不依赖 dev server） |

组件**不取数**：`/wrong-questions` 由你的页面继续请求，我只吃现成的 `items` 与 `weak_points`，
所以不会和你的 loading、错误处理、409 逻辑打架。

## 二、接入三步（改 2 处，约 3 分钟）

### 第 1 步：确认文件已在

```
frontend/src/components/StatsCard.vue
frontend/src/components/WeaknessChart.vue
frontend/src/utils/wrongStats.js
```

### 第 2 步：在 `WrongBookView.vue` 的 `<script setup>` 里加 4 行

```js
// 顶部 import 区
import StatsCard from '@/components/StatsCard.vue'
import WeaknessChart from '@/components/WeaknessChart.vue'
import { summarizeWrongBook } from '@/utils/wrongStats'

// 现有 const weakPoints = ref([]) 之后
const stats = computed(() =>
  summarizeWrongBook({ items: list.value, weak_points: weakPoints.value })
)
const hardCount = computed(() =>
  weakPoints.value.filter((w) => (Number(w?.wrong_count) || 0) >= 3).length
)
```

> `computed` 你已经在用了（`hasOptions`），不用另外 import。
> 接口目前一次性返回全部错题，`total` 与 `items.length` 一致；**将来若加分页**，
> 把 `total: total.value` 一起传进去即可，其余不用改。

### 第 3 步：在列表视图 `<el-card v-if="!detail" class="glass-card" shadow="never">` 里，
紧跟在开标签之后插入下面这段（在「薄弱知识点：」标签行之前）：

```html
<!-- 统计区：吴雅晴 StatsCard + WeaknessChart -->
<div
  class="wb-stats"
  style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:14px;"
>
  <StatsCard
    label="错题总数" :value="stats.total" unit="题" tone="primary"
    :hint="`覆盖 ${stats.weakCount} 个知识点`" :loading="loading"
  />
  <StatsCard
    label="未掌握" :value="stats.unmastered" unit="题" tone="danger"
    hint="连对 2 次自动转已掌握" :loading="loading"
  />
  <StatsCard
    label="已掌握" :value="stats.mastered" unit="题" tone="success"
    :hint="`掌握率 ${stats.rate}%`" :loading="loading"
  />
  <StatsCard
    label="薄弱知识点" :value="stats.weakCount" unit="个" tone="warning"
    :hint="`错 ≥3 次的有 ${hardCount} 个`" :loading="loading"
  />
</div>

<WeaknessChart
  v-if="!loading"
  :weak-points="weakPoints"
  :max-rows="6"
  style="margin-bottom:14px;"
/>
<!-- 统计区结束 -->
```

> 用内联 style 是为了不碰你的 `style.css` 与 scoped 样式；如果你更想写进样式表，
> 把 `style="..."` 换成一个类名即可，网格列参数是一样的。

## 三、口径（写论文/答辩可以直接用）

| 指标 | 算法 | 说明 |
| --- | --- | --- |
| 错题总数 | `items.length`（或后端 `total`） | 一行一道错题，重复答错不新增行 |
| 未掌握 | `total − 已掌握` | 与列表「状态」列同源 |
| 已掌握 | `items.filter(mastered)` | 连对 2 次由后端置位 |
| 薄弱知识点 | `weak_points` 中 `weakness ≠ 已掌握` 的个数 | 已掌握的知识点不计入薄弱 |
| 薄弱度 | 后端 `weakness` 优先；缺失时按错题次数推：≥3 高、2 中、1 低 | 与 `wrong_book.py` 的 `weakness` 口径一致 |
| 条形长度 | 按最大错题次数等比缩放到 428px，最小 6px | 没有轨道参照就看不出比例，所以画了浅灰底槽 |

## 四、怎么算做完（验收清单）

1. `cd frontend && npm run build` → 构建通过，无新增依赖告警。
2. `node --test tests/wrongStats.test.mjs` → **9 项全绿**（我本地已跑，v24.21.0）。
3. 打开错题页：
   - 四个数字与下方列表条数对得上（已掌握 + 未掌握 = 总数）；
   - 薄弱知识点数与「薄弱知识点：」标签行的知识点个数一致；
   - 条形图按错题次数从多到少，颜色随高/中/低变化。
4. 无错题账号：四张卡显示 `0`，图表区显示「暂无错题数据，先去做一次智能自测」，不报错。
5. 接口失败：页面原有 `ElMessage.error` 提示不变（组件不参与请求）。

## 五、已知限制

- 统计范围是整个错题本，不是当前筛选结果；11.30 筛器上线后如果要「随筛选联动」，
  把 `list` 换成筛选后的数组即可，组件不用改。
- 图表最多画 6 行，多的不画（不是截断数据），需要看全量可以调 `:max-rows`。
- 颜色全部走 CSS 变量并带兜底值，梁倩的令牌（`--c-primary` 等）上线后自动生效，不用改组件。
- 12.02 我会补截图包与裸模型对比图，这一版先给可用组件与静态预览。
