<template>
  <div class="page">
    <div class="page-head">
      <h2>错题本</h2>
      <el-tag v-if="USE_MOCK" type="warning" size="small">
        模拟数据（后端接口上线后把 USE_MOCK 改成 false）
      </el-tag>
    </div>
    <p class="hint">
      按知识点聚合，错得越多越靠前；重做连对 2 次自动标记「已掌握」。
    </p>

    <!-- 列表 -->
    <el-card v-if="!detail" class="glass-card" shadow="never">
      <div v-if="weakPoints.length" class="weak-row">
        <span class="weak-label">薄弱知识点：</span>
        <el-tag
          v-for="w in weakPoints"
          :key="w.knowledge_name"
          size="small"
          :type="w.weakness === '高' ? 'danger' : (w.weakness === '中' ? 'warning' : 'info')"
          style="margin-right: 6px;"
        >{{ w.knowledge_name }} · {{ w.weakness }}（错 {{ w.wrong_count }} 次）</el-tag>
      </div>
      <el-table :data="list" v-loading="loading" style="width: 100%;">
        <el-table-column prop="knowledge_name" label="知识点" min-width="160" />
        <el-table-column prop="wrong_count" label="错题次数" width="100" />
        <el-table-column label="连对" width="80">
          <template #default="{ row }">{{ row.correct_streak || 0 }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.mastered ? 'success' : 'info'" size="small">
              {{ row.mastered ? '已掌握' : '未掌握' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openDetail(row)">查看 / 重做</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-if="!loading && list.length === 0"
        description="还没有错题，先去做一次智能自测吧"
      >
        <el-button type="primary" @click="router.push('/self-tests')">去自测</el-button>
      </el-empty>
    </el-card>

    <!-- 详情 + 重做 -->
    <el-card v-else class="glass-card" shadow="never">
      <div class="detail-head">
        <el-button size="small" @click="detail = null">← 返回列表</el-button>
        <el-tag type="info" size="small">{{ detail.knowledge_name }}</el-tag>
        <el-tag v-if="detail.mastered" type="success" size="small">已掌握</el-tag>
      </div>

      <div class="stem">{{ detail.question_stem }}</div>

      <!-- 后端返回了选项就做单选；没返回就退化为文本输入 -->
      <el-radio-group
        v-if="hasOptions"
        v-model="retryAnswer"
        class="options"
        :disabled="retrying"
      >
        <el-radio
          v-for="opt in optionsOf(detail)"
          :key="opt.value"
          :label="opt.value"
          :value="opt.value"
          border
        >{{ opt.label }}</el-radio>
      </el-radio-group>
      <el-input
        v-else
        v-model="retryAnswer"
        :disabled="retrying"
        placeholder="输入你的答案（选择题填字母，如 B；判断题填 对 / 错）"
        style="max-width: 420px;"
      />

      <div class="actions">
        <el-button
          type="primary"
          :loading="retrying"
          :disabled="!retryAnswer"
          @click="retry"
        >重做提交</el-button>
      </div>

      <el-alert
        v-if="retryResult"
        :type="retryResult.is_correct ? 'success' : 'error'"
        :closable="false"
        show-icon
        style="margin-top: 16px;"
        :title="retryResult.is_correct
          ? `答对了，当前连对 ${retryResult.correct_streak} 次`
          : '答错了，连对次数已清零'"
      >
        <div style="margin-bottom: 4px;">正确答案：<b>{{ detail.correct_answer }}</b></div>
        <div style="margin-bottom: 4px;">{{ detail.analysis || '（后端未返回解析）' }}</div>
        <div v-if="detail.evidence_page">出处：第 {{ detail.evidence_page }} 页</div>
        <div v-if="retryResult.mastered" style="margin-top: 6px; font-weight: 600;">
          🎉 连对 2 次，已标记为「已掌握」
        </div>
      </el-alert>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/utils/http'

// ⚠️ 后端接口上线后，把这里改成 false 即可切到真实接口
const USE_MOCK = false

const router = useRouter()

const list = ref([])
const weakPoints = ref([])
const loading = ref(false)
const detail = ref(null)
const retryAnswer = ref('')
const retrying = ref(false)
const retryResult = ref(null)

const hasOptions = computed(() =>
  Array.isArray(detail.value?.options) && detail.value.options.length > 0
)

onMounted(load)

async function load() {
  loading.value = true
  try {
    if (USE_MOCK) {
      list.value = MOCK_LIST.map(x => ({ ...x }))
      return
    }
    // 后端返回 { items, weak_points, total }，不是数组
    const data = await http.get('/wrong-questions')
    list.value = data?.items || []
    weakPoints.value = data?.weak_points || []
  } catch (e) {
    ElMessage.error('读取错题本失败：' + (e?.message || '网络错误'))
  } finally {
    loading.value = false
  }
}

async function openDetail(row) {
  try {
    if (USE_MOCK) {
      detail.value = { ...MOCK_DETAIL[row.wrong_id] }
    } else {
      // 错题详情（含解析与出处）
      detail.value = await http.get(`/wrong-questions/${row.wrong_id}`)
    }
    retryAnswer.value = ''
    retryResult.value = null
  } catch (e) {
    ElMessage.error('读取错题详情失败：' + (e?.message || '网络错误'))
  }
}

function optionsOf(item) {
  const opts = item.options || []
  return opts.map((text, i) => {
    const s = String(text)
    const m = s.match(/^\s*([A-Da-d])[.、．\s]/)
    const value = m ? m[1].toUpperCase() : String.fromCharCode(65 + i)
    return { value, label: s }
  })
}

async function retry() {
  retrying.value = true
  try {
    if (USE_MOCK) {
      const ok = String(retryAnswer.value).trim().toUpperCase()
        === String(detail.value.correct_answer).trim().toUpperCase()
      const streak = ok ? (detail.value.correct_streak || 0) + 1 : 0
      const mastered = streak >= 2

      retryResult.value = { is_correct: ok, correct_streak: streak, mastered }
      detail.value.correct_streak = streak
      detail.value.mastered = mastered

      const row = list.value.find(x => x.wrong_id === detail.value.wrong_id)
      if (row) {
        row.correct_streak = streak
        row.mastered = mastered
      }
    } else {
      // 重做一题：判定对错、更新连对次数与掌握状态
      retryResult.value = await http.post(`/wrong-questions/${detail.value.wrong_id}/retry`, {
        answer: retryAnswer.value
      })
      detail.value.correct_streak = retryResult.value.correct_streak
      detail.value.mastered = retryResult.value.mastered
      await load() // 刷新列表里的连对 / 掌握状态
    }
  } catch (e) {
    ElMessage.error('重做失败：' + (e?.message || '网络错误'))
  } finally {
    retrying.value = false
  }
}

// ---------- 以下为模拟数据，后端接口上线后可删掉 ----------
const MOCK_LIST = [
  { wrong_id: 1, knowledge_name: '构件与对象的区别', wrong_count: 2, correct_streak: 0, mastered: false },
  { wrong_id: 2, knowledge_name: '开闭原则', wrong_count: 1, correct_streak: 1, mastered: false }
]

const MOCK_DETAIL = {
  1: {
    wrong_id: 1,
    knowledge_name: '构件与对象的区别',
    question_stem: '关于「构件」与「对象」的区别，下列说法正确的是？',
    options: [
      'A 构件是运行时实例，对象是可部署单元',
      'B 构件是可部署单元，对象是运行时实例',
      'C 两者没有区别，只是叫法不同',
      'D 构件只能包含一个对象'
    ],
    correct_answer: 'B',
    analysis: '构件是可独立部署的单元；对象是运行时创建的实例，构件通过接口对外提供服务。',
    evidence_page: 5,
    correct_streak: 0,
    mastered: false
  },
  2: {
    wrong_id: 2,
    knowledge_name: '开闭原则',
    question_stem: '下列哪一项最符合「开闭原则」的含义？',
    options: [
      'A 对扩展开放，对修改关闭',
      'B 对修改开放，对扩展关闭',
      'C 所有代码都必须公开',
      'D 模块之间不允许依赖'
    ],
    correct_answer: 'A',
    analysis: '开闭原则要求软件实体对扩展开放、对修改关闭，通过抽象与多态实现。',
    evidence_page: 12,
    correct_streak: 1,
    mastered: false
  }
}
</script>

<style scoped>
.page {
  max-width: 860px;
  margin: 0 auto;
  padding: 24px 20px 40px;
}

.page-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.page-head h2 {
  margin: 0;
}

.hint {
  color: #606266;
  font-size: 13px;
  margin: 6px 0 18px;
}

.weak-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}

.weak-label {
  color: #606266;
  font-size: 13px;
}

.detail-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
}

.stem {
  font-size: 16px;
  line-height: 1.7;
  margin-bottom: 18px;
  color: #303133;
}

.options {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}

.options :deep(.el-radio) {
  margin-right: 0;
}

.actions {
  margin-top: 20px;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
