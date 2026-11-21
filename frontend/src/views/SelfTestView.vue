<template>
  <div class="page">
    <div class="page-head">
      <h2>智能自测</h2>
      <el-tag v-if="USE_MOCK" type="warning" size="small">
        模拟数据（后端接口上线后把 USE_MOCK 改成 false）
      </el-tag>
    </div>
    <p class="hint">
      选一份已整理好的课件，系统出题；交卷后逐题显示对错、正确答案、解析和出处页码。
    </p>

    <!-- 第一步：选任务、组卷 -->
    <el-card v-if="!paper" class="glass-card" shadow="never">
      <el-form label-width="90px">
        <el-form-item label="整理任务">
          <el-select
            v-model="sessionId"
            placeholder="选择一个已完成的任务"
            style="width: 100%;"
            :loading="loadingSessions"
          >
            <el-option
              v-for="s in sessions"
              :key="s.session_id"
              :label="`#${s.session_id} ${s.course_name || '未命名课程'}（${s.source_file || ''}）`"
              :value="s.session_id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="题量">
          <el-select v-model="questionCount" style="width: 120px;">
            <el-option :value="3" label="3 题" />
            <el-option :value="5" label="5 题" />
          </el-select>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="creating" @click="createTest">生成自测</el-button>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="!loadingSessions && sessions.length === 0"
        type="warning"
        :closable="false"
        show-icon
        title="还没有已完成的整理任务"
        description="先到「上传课件」上传并整理一份课件，再来做自测。"
      />
    </el-card>

    <!-- 第二步：答题 -->
    <el-card v-else-if="!result" class="glass-card" shadow="never">
      <div class="paper-head">
        <span>第 {{ currentIndex + 1 }} / {{ paper.items.length }} 题</span>
        <el-tag v-if="currentItem.knowledge_name" type="info" size="small">
          {{ currentItem.knowledge_name }}
        </el-tag>
      </div>

      <div class="stem">{{ currentItem.stem }}</div>

      <el-radio-group v-model="answers[currentIndex]" class="options">
        <el-radio
          v-for="opt in optionsOf(currentItem)"
          :key="opt.value"
          :label="opt.value"
          :value="opt.value"
          border
        >
          {{ opt.label }}
        </el-radio>
      </el-radio-group>

      <div class="actions">
        <el-button :disabled="currentIndex === 0" @click="currentIndex--">上一题</el-button>
        <el-button
          v-if="currentIndex < paper.items.length - 1"
          type="primary"
          @click="currentIndex++"
        >下一题</el-button>
        <el-button v-else type="success" :loading="submitting" @click="submit">交卷</el-button>
      </div>
    </el-card>

    <!-- 第三步：批改结果 -->
    <el-card v-else class="glass-card" shadow="never">
      <div class="score-line">
        得分 <b>{{ result.score }}</b> / 100
        <span class="score-sub">答对 {{ result.correct_count }} 题，答错 {{ result.wrong_count }} 题</span>
      </div>

      <div v-for="(item, i) in result.items" :key="item.item_id" class="result-item">
        <div class="result-head">
          <el-tag :type="item.is_correct ? 'success' : 'danger'" size="small">
            {{ item.is_correct ? '答对' : '答错' }}
          </el-tag>
          <span>第 {{ i + 1 }} 题</span>
          <el-tag v-if="item.evidence_page" type="info" size="small">
            出处：第 {{ item.evidence_page }} 页
          </el-tag>
        </div>

        <div class="result-stem">{{ stemOf(item.item_id) }}</div>
        <div class="result-answer">正确答案：<b>{{ item.correct_answer }}</b></div>
        <div class="result-analysis">{{ item.analysis || '（后端未返回解析）' }}</div>
      </div>

      <div class="actions">
        <el-button type="primary" @click="reset">再测一次</el-button>
        <el-button @click="router.push('/wrong-book')">去错题本</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/utils/http'

// ⚠️ 后端接口上线后，把这里改成 false 即可切到真实接口
const USE_MOCK = false

const router = useRouter()

const sessions = ref([])
const loadingSessions = ref(false)
const sessionId = ref(null)
const questionCount = ref(5)

const creating = ref(false)
const submitting = ref(false)

const paper = ref(null) // 取卷结果：{ test_id, items: [...] }
const currentIndex = ref(0)
const answers = reactive([]) // 与 paper.items 一一对应
const result = ref(null) // 交卷结果：{ score, correct_count, wrong_count, items }

const currentItem = computed(() =>
  paper.value ? paper.value.items[currentIndex.value] : {}
)

onMounted(loadSessions)

async function loadSessions() {
  loadingSessions.value = true
  try {
    if (USE_MOCK) {
      sessions.value = MOCK_SESSIONS
      return
    }
    const list = await http.get('/sessions')
    // 只有整理完成（success / partial）的任务才能做自测
    sessions.value = (list || []).filter(s => ['success', 'partial'].includes(s.status))
  } catch (e) {
    ElMessage.error('读取任务列表失败：' + (e?.message || '网络错误'))
  } finally {
    loadingSessions.value = false
  }
}

async function createTest() {
  if (!sessionId.value) return ElMessage.warning('请先选择一个整理任务')
  creating.value = true
  try {
    if (USE_MOCK) {
      paper.value = {
        test_id: 1,
        items: MOCK_ITEMS.slice(0, questionCount.value)
      }
    } else {
      // 组卷：POST /api/self-tests → 拿 test_id
      const created = await http.post('/self-tests', {
        session_id: sessionId.value,
        question_count: questionCount.value,
        scope_text: ''
      })
      // 取卷：GET /api/self-tests/{id}（答案不下发）
      // 后端是异步出题（接口先返回 draft），这里轮询到 ready 为止，最多等 20 秒
      paper.value = await http.get(`/self-tests/${created.test_id}`)
      let tries = 0
      while (!['ready', 'graded', 'failed'].includes(paper.value?.status) && tries < 40) {
        await new Promise(resolve => setTimeout(resolve, 500))
        paper.value = await http.get(`/self-tests/${created.test_id}`)
        tries += 1
      }
      if (paper.value?.status === 'failed') {
        throw new Error(paper.value.error_message || '出题失败，请重新组卷')
      }
      if (!paper.value?.items?.length) {
        throw new Error('题目还在生成中，请稍后重试')
      }
    }

    currentIndex.value = 0
    answers.length = paper.value.items.length
    answers.fill('')
    result.value = null
  } catch (e) {
    ElMessage.error('生成自测失败：' + (e?.message || '网络错误'))
  } finally {
    creating.value = false
  }
}

// 把一道题转成单选项：
// - 判断题固定「对 / 错」
// - 单选题把 "A xxx" 取首字母作为提交值（与契约示例 answer:"B" 一致）
function optionsOf(item) {
  if (item.question_type === 'judge') {
    return [
      { value: '对', label: '对' },
      { value: '错', label: '错' }
    ]
  }
  return (item.options || []).map((text, i) => {
    const s = String(text)
    const m = s.match(/^\s*([A-Da-d])[.、．\s]/)
    const value = m ? m[1].toUpperCase() : String.fromCharCode(65 + i)
    return { value, label: s }
  })
}

async function submit() {
  if (answers.some(a => !a)) {
    return ElMessage.warning('还有题目没作答，先补全再交卷')
  }
  submitting.value = true
  try {
    if (USE_MOCK) {
      result.value = gradeLocally(paper.value.items, answers)
    } else {
      // 交卷：POST /api/self-tests/{id}/submit
      result.value = await http.post(`/self-tests/${paper.value.test_id}/submit`, {
        answers: paper.value.items.map((item, i) => ({
          item_id: item.item_id,
          answer: answers[i]
        }))
      })
    }
    ElMessage.success('交卷成功')
  } catch (e) {
    ElMessage.error('交卷失败：' + (e?.message || '网络错误'))
  } finally {
    submitting.value = false
  }
}

// 模拟批改：真实环境由后端判分，这里只用于本地预览
function gradeLocally(items, ans) {
  const graded = items.map((item, i) => {
    const ok = String(ans[i]).trim().toUpperCase() === String(item.answer).trim().toUpperCase()
    return {
      item_id: item.item_id,
      is_correct: ok,
      correct_answer: item.answer,
      analysis: item.analysis,
      evidence_page: item.evidence_page
    }
  })
  const correct = graded.filter(g => g.is_correct).length
  return {
    score: Math.round((correct / graded.length) * 100),
    correct_count: correct,
    total: graded.length,
    wrong_count: graded.length - correct,
    items: graded
  }
}

function stemOf(itemId) {
  const q = paper.value?.items.find(x => x.item_id === itemId)
  return q?.stem || ''
}

function reset() {
  paper.value = null
  result.value = null
  currentIndex.value = 0
}

// ---------- 以下为模拟数据，后端接口上线后可删掉 ----------
const MOCK_SESSIONS = [
  { session_id: 8, course_name: '软件工程', source_file: '9_副本.pdf', status: 'success' }
]

const MOCK_ITEMS = [
  {
    item_id: 11,
    seq: 1,
    question_type: 'single',
    stem: '关于「构件」与「对象」的区别，下列说法正确的是？',
    options: [
      'A 构件是运行时实例，对象是可部署单元',
      'B 构件是可部署单元，对象是运行时实例',
      'C 两者没有区别，只是叫法不同',
      'D 构件只能包含一个对象'
    ],
    knowledge_name: '构件与对象的区别',
    answer: 'B',
    analysis: '构件是可独立部署的单元；对象是运行时创建的实例，构件通过接口对外提供服务。',
    evidence_page: 5
  },
  {
    item_id: 12,
    seq: 2,
    question_type: 'judge',
    stem: '「一个构件只能提供一个接口」——这个说法对吗？',
    knowledge_name: '构件接口',
    answer: '错',
    analysis: '一个构件可以提供多个接口，接口是构件对外服务的契约。',
    evidence_page: 6
  },
  {
    item_id: 13,
    seq: 3,
    question_type: 'single',
    stem: '下列哪一项最符合「开闭原则」的含义？',
    options: [
      'A 对扩展开放，对修改关闭',
      'B 对修改开放，对扩展关闭',
      'C 所有代码都必须公开',
      'D 模块之间不允许依赖'
    ],
    knowledge_name: '开闭原则',
    answer: 'A',
    analysis: '开闭原则要求软件实体对扩展开放、对修改关闭，通过抽象与多态实现。',
    evidence_page: 12
  },
  {
    item_id: 14,
    seq: 4,
    question_type: 'judge',
    stem: '「构件必须通过明确定义的接口对外提供服务」——这个说法对吗？',
    knowledge_name: '构件接口',
    answer: '对',
    analysis: '构件通过接口（提供接口 / 需求接口）与外界交互，接口是构件的对外契约。',
    evidence_page: 7
  },
  {
    item_id: 15,
    seq: 5,
    question_type: 'single',
    stem: '构件级设计的主要产出是什么？',
    options: [
      'A 需求规格说明书',
      'B 构件图、接口描述与构件级设计类图',
      'C 项目进度计划',
      'D 用户手册'
    ],
    knowledge_name: '构件级设计',
    answer: 'B',
    analysis: '构件级设计细化设计模型，产出构件、接口、部署关系等设计制品。',
    evidence_page: 3
  }
]
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

.paper-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  color: #606266;
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
  margin-top: 24px;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.score-line {
  font-size: 18px;
  margin-bottom: 20px;
}

.score-line b {
  font-size: 26px;
  color: #409eff;
}

.score-sub {
  margin-left: 16px;
  color: #909399;
  font-size: 13px;
}

.result-item {
  padding: 14px 16px;
  margin-bottom: 12px;
  background: rgba(255, 255, 255, 0.35);
  border-radius: 10px;
}

.result-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  color: #606266;
  font-size: 13px;
}

.result-stem {
  color: #303133;
  margin-bottom: 6px;
  line-height: 1.6;
}

.result-answer {
  color: #303133;
  margin-bottom: 4px;
}

.result-analysis {
  color: #606266;
  font-size: 13px;
  line-height: 1.7;
}
</style>
