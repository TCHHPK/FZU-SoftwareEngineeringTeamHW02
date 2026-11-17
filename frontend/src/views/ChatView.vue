<template>
  <div style="padding: 20px; max-width: 860px; margin: 0 auto;">
    <h2>课程问答</h2>
    <p style="color: #909399; font-size: 13px; margin-top: -6px;">
      只依据你上传的材料回答；材料里没有的内容会如实说明，不会编造。
    </p>

    <div class="chat-container">
      <div v-for="(m, i) in messages" :key="i"
           :style="{ textAlign: m.role === 'user' ? 'right' : 'left', marginBottom: '16px' }">
        <el-tag :type="tagType(m.role)" size="small" style="margin-bottom: 5px;">
          {{ m.role === 'user' ? '我' : (m.role === 'system' ? '系统提示' : 'AI 助手') }}
        </el-tag>

        <div :style="bubbleStyle(m.role)">
          {{ m.content }}
        </div>

        <!-- 回答依据：每条都可追到课件页码 -->
        <div v-if="m.evidence && m.evidence.length" style="margin-top: 6px;">
          <el-tag v-for="(ev, ei) in m.evidence" :key="ei" size="small" type="info"
                  style="margin-right: 6px;">
            {{ evidenceLabel(ev) }}
          </el-tag>
        </div>
        <div v-if="m.insufficient" style="margin-top: 6px; color: #e6a23c; font-size: 12px;">
          本次回答为「材料依据不足」，没有生成内容。
        </div>
      </div>

      <el-empty v-if="messages.length === 0" description="有什么想问的？先上传课件再提问效果更好。" />
    </div>

    <!-- 没有材料时给出可操作的提示，而不是让用户干等 -->
    <el-alert
      v-if="noMaterial"
      title="还没有可用的材料"
      description="问答只基于你上传的课件。请先到「上传课件」上传一份 PDF 或 PPT，再回来提问。"
      type="warning"
      show-icon
      :closable="false"
      style="margin-bottom: 12px;"
    />

    <div style="display: flex; gap: 10px;">
      <el-input v-model="question" placeholder="输入你的问题，例如：构件与对象有什么区别？"
                @keyup.enter="ask" size="large" :disabled="loading" />
      <el-button type="primary" size="large" :loading="loading" @click="ask">发送</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import http from '@/utils/http'

const question = ref('')
const messages = ref([])
const loading = ref(false)
const noMaterial = ref(false)

const MATERIAL_HINT = ['还没有可用材料', '上传课件']

function tagType(role) {
  if (role === 'user') return 'primary'
  if (role === 'system') return 'warning'
  return 'success'
}

function bubbleStyle(role) {
  const base = {
    display: 'inline-block',
    padding: '10px 15px',
    borderRadius: '8px',
    maxWidth: '80%',
    textAlign: 'left',
    boxShadow: '0 2px 5px rgba(0,0,0,0.08)',
    whiteSpace: 'pre-wrap',
    lineHeight: '1.6'
  }
  if (role === 'user') return { ...base, background: '#409eff', color: '#fff' }
  if (role === 'system') return { ...base, background: '#fdf6ec', color: '#b88230' }
  return { ...base, background: '#fff', color: '#303133' }
}

function evidenceLabel(ev) {
  if (!ev) return '出处未知'
  if (ev.page_num) return `第 ${ev.page_num} 页`
  if (ev.slide_index) return `第 ${ev.slide_index} 张幻灯片`
  return ev.chapter_title || '出处未知'
}

async function ask() {
  if (!question.value.trim() || loading.value) return

  const q = question.value.trim()
  messages.value.push({ role: 'user', content: q })
  question.value = ''
  loading.value = true

  try {
    const res = await http.post('/chat/ask', { question: q })
    messages.value.push({
      role: 'assistant',
      content: res.answer || '（后端没有返回内容）',
      evidence: res.evidence || [],
      insufficient: !!res.insufficient
    })
    noMaterial.value = false
  } catch (e) {
    // 关键：失败时如实告知，绝不编造答案。
    // 原实现会返回一段写死的"构件是系统中可部署的单元"，与问题无关，
    // 属于典型的伪造内容，已删除。
    const msg = String(e?.message || '请求失败')
    messages.value.push({
      role: 'system',
      content: `回答失败：${msg}\n请检查材料是否已上传、服务器是否已配置模型密钥，然后重试。`
    })
    noMaterial.value = MATERIAL_HINT.some(h => msg.includes(h))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* 毛玻璃对话容器 */
.chat-container {
  backdrop-filter: blur(15px);
  -webkit-backdrop-filter: blur(15px);
  background: rgba(255, 255, 255, 0.15) !important;
  border: 1px solid rgba(255, 255, 255, 0.4);
  border-radius: 12px;
  height: 550px;
  padding: 25px;
  margin: 16px 0;
  overflow-y: auto;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.05);
}

/* 毛玻璃输入框 */
:deep(.el-input__wrapper) {
  backdrop-filter: blur(5px);
  -webkit-backdrop-filter: blur(5px);
  background: rgba(255, 255, 255, 0.25) !important;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}
</style>
