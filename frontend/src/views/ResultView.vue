<template>
  <div style="padding: 40px; max-width: 960px; margin: 0 auto;" v-loading="loading">
    <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
      <h2 style="margin: 0;">整理结果</h2>
      <el-tag v-if="courseName" type="info">{{ courseName }}</el-tag>
      <el-tag v-if="status === 'partial'" type="warning">部分内容有告警</el-tag>
    </div>

    <el-alert
      v-if="errorMessage"
      :title="errorMessage"
      type="error"
      show-icon
      style="margin-top: 20px;"
    />

    <template v-if="!errorMessage">
      <!-- 材料/结果本身的告警 -->
      <el-alert
        v-for="(w, i) in warnings"
        :key="'w' + i"
        :title="w"
        type="warning"
        :closable="false"
        show-icon
        style="margin-top: 12px;"
      />
      <!-- 实现说明（例如占位实现），不影响任务状态 -->
      <el-alert
        v-for="(n, i) in notices"
        :key="'n' + i"
        :title="n"
        type="info"
        :closable="false"
        show-icon
        style="margin-top: 12px;"
      />

      <!-- 质量自评：按 85% / 10% / 5% 加权 -->
      <el-card v-if="quality" shadow="never" style="margin-top: 20px;">
        <div style="display: flex; align-items: center; gap: 24px; flex-wrap: wrap;">
          <div>
            <div style="color: #909399; font-size: 12px;">整理质量自评</div>
            <div style="font-size: 28px; font-weight: 600; color: #409eff;">
              {{ quality.total }}<span style="font-size: 14px; color: #909399;"> / 100</span>
            </div>
          </div>
          <div style="display: flex; gap: 20px; flex-wrap: wrap;">
            <div v-for="d in qualityDimensions" :key="d.label">
              <div style="color: #909399; font-size: 12px;">{{ d.label }}</div>
              <div style="font-size: 16px;">{{ d.value }}</div>
            </div>
          </div>
        </div>
        <ul v-if="quality.reasons && quality.reasons.length"
            style="margin: 12px 0 0 0; padding-left: 20px; color: #606266; font-size: 13px;">
          <li v-for="(r, i) in quality.reasons" :key="i">{{ r }}</li>
        </ul>
        <p v-if="droppedItems > 0"
           style="margin: 10px 0 0 0; color: #e6a23c; font-size: 13px;">
          有 {{ droppedItems }} 条内容因无法在原文中核验出处而被丢弃（这正是防编造机制在起作用）。
        </p>
      </el-card>

      <el-tabs style="margin-top: 24px;" v-model="activeTab">
        <!-- 1. 结构化笔记：按章节分组，每条带出处角标 -->
        <el-tab-pane label="结构化笔记" name="note">
          <el-empty v-if="groups.length === 0" description="没有生成结构化笔记" />
          <div v-for="(group, gi) in groups" :key="gi" style="margin-bottom: 28px;">
            <h3 style="margin: 0 0 12px 0; padding-left: 8px; border-left: 4px solid #409eff;">
              {{ group.title }}
            </h3>
            <div v-for="(item, ii) in group.items" :key="ii"
                 style="margin-bottom: 16px; padding: 12px 14px; background: #fafafa; border-radius: 6px;">
              <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 6px;">
                <strong>{{ item.name }}</strong>
                <el-tag v-for="(ev, ei) in item.evidence" :key="ei" size="small" type="info">
                  {{ evidenceLabel(ev) }}
                </el-tag>
                <SourceBadge v-if="item.evidence && item.evidence.length" :source="item.evidence[0]" />
                <el-tag v-else type="danger" size="small">无出处</el-tag>
              </div>
              <p v-if="item.definition"
                 style="margin: 8px 0 0 0; line-height: 1.7; color: #303133;">
                {{ item.definition }}
              </p>
              <ul v-if="item.key_points && item.key_points.length"
                  style="margin: 6px 0 0 0; padding-left: 20px; color: #606266; line-height: 1.7;">
                <li v-for="(kp, ki) in item.key_points" :key="ki">{{ kp }}</li>
              </ul>
              <p v-if="item.formula_latex"
                 style="margin: 8px 0 0 0; font-family: Consolas, monospace; color: #c7254e;">
                $$ {{ item.formula_latex }} $$
              </p>
            </div>
          </div>
        </el-tab-pane>

        <!-- 2. 重点清单 -->
        <el-tab-pane label="重点清单" name="keypoints">
          <el-empty v-if="keyPoints.length === 0" description="没有生成重点清单" />
          <ol style="padding-left: 22px; line-height: 2;">
            <li v-for="(k, i) in keyPoints" :key="i">{{ k }}</li>
          </ol>
        </el-tab-pane>

        <!-- 3. 文本思维导图 -->
        <el-tab-pane label="文本思维导图" name="mindmap">
          <el-empty v-if="!mindMap" description="没有生成思维导图" />
          <pre v-else
               style="background: #f5f7fa; padding: 20px; border-radius: 8px;
                      white-space: pre-wrap; line-height: 1.8;
                      font-family: Consolas, monospace;">{{ mindMap }}</pre>
        </el-tab-pane>
      </el-tabs>

      <div style="margin-top: 32px; display: flex; gap: 12px; flex-wrap: wrap;">
        <el-button type="primary" :loading="exporting === 'docx'" @click="exportFile('docx')">
          导出 Word
        </el-button>
        <el-button :loading="exporting === 'md'" @click="exportFile('md')">
          导出 Markdown
        </el-button>
        <el-button type="success" :loading="exporting === 'tex'" @click="exportFile('tex')">
          导出 LaTeX
        </el-button>
        <!-- 后续还有课件时，从这里追加材料，会与已有材料合并重新整理 -->
        <el-button
          v-if="['success', 'partial'].includes(status)"
          type="warning"
          plain
          @click="router.push(`/upload?append=${route.params.id}`)"
        >
          补充材料并合并
        </el-button>
        <el-button @click="router.push('/sessions')">返回历史任务</el-button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/utils/http'
import SourceBadge from '@/components/SourceBadge.vue'

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const exporting = ref('')
const errorMessage = ref('')
const activeTab = ref('note')

const courseName = ref('')
const status = ref('')
const items = ref([])
const keyPoints = ref([])
const mindMap = ref('')
const quality = ref(null)
const droppedItems = ref(0)
const warnings = ref([])
const notices = ref([])

const qualityDimensions = computed(() => {
  const q = quality.value
  if (!q) return []
  return [
    { label: '核心功能完成度（85%）', value: q.core },
    { label: '结构化与规范性（10%）', value: q.structure },
    { label: '拓展关联（5%）', value: q.extension }
  ]
})

// 按章节把知识点分组：章名取自证据里的 chapter_title，没有则归到「未标注章节」
const groups = computed(() => {
  const map = new Map()
  for (const item of items.value) {
    const chapter = item?.evidence?.[0]?.chapter_title || '未标注章节'
    if (!map.has(chapter)) map.set(chapter, [])
    map.get(chapter).push(item)
  }
  return [...map.entries()].map(([title, list]) => ({ title, items: list }))
})

function evidenceLabel(ev) {
  if (!ev) return '出处未知'
  if (ev.page_num) return `第 ${ev.page_num} 页`
  if (ev.slide_index) return `第 ${ev.slide_index} 张幻灯片`
  return ev.chapter_title || '出处未知'
}

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await http.get(`/sessions/${route.params.id}/result`)
    courseName.value = data.course_name || ''
    status.value = data.status || ''
    items.value = data.items || []
    keyPoints.value = data.key_points || []
    mindMap.value = data.mindmap_text || ''
    quality.value = data.quality || null
    droppedItems.value = data.dropped_items || 0
    warnings.value = data.warnings || []
    notices.value = data.notices || []
  } catch (e) {
    const msg = String(e?.message || '')
    // 后端在任务未完成时返回 code=1「任务仍在处理中」，此时应回到进度页而不是报错
    if (msg.includes('处理中') || msg.includes('仍在处理')) {
      ElMessage.info('任务仍在处理中，已为你打开进度页')
      router.replace(`/sessions/${route.params.id}/progress`)
      return
    }
    errorMessage.value = msg || '结果加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

async function exportFile(fmt) {
  exporting.value = fmt
  try {
    // 拦截器对 blob 已做特殊处理，返回值就是 Blob
    const blob = await http.get(`/sessions/${route.params.id}/export`, {
      params: { fmt },
      responseType: 'blob'
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const safeName = (courseName.value || '课程笔记').replace(/[\\/:*?"<>|]/g, '_')
    const EXT = { docx: 'docx', md: 'md', tex: 'tex' }
    a.href = url
    a.download = `${safeName}.${EXT[fmt] || fmt}`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${a.download}`)
  } catch (e) {
    if (!e?.message) ElMessage.error('导出失败，请稍后重试')
  } finally {
    exporting.value = ''
  }
}

onMounted(load)
</script>
