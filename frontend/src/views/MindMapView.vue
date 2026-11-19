<template>
  <div class="mindmap-page" v-loading="loading">
    <div class="page-heading">
      <div>
        <el-button link @click="router.push(`/sessions/${route.params.id}/result`)">← 返回整理结果</el-button>
        <h2>图形化思维导图 <el-tag size="small" type="primary">U15</el-tag></h2>
        <p>任务 #{{ route.params.id }}<span v-if="courseName"> · {{ courseName }}</span> · 章节与知识点的可视化结构</p>
      </div>
      <div class="page-actions">
        <el-button :disabled="loading || building" @click="loadMindmap">刷新</el-button>
        <el-button type="primary" :loading="building" :disabled="loading"
          @click="buildMindmap">生成 / 重建导图</el-button>
      </div>
    </div>
    <el-alert v-if="previewMode" type="warning" show-icon :closable="false"
      class="page-alert" title="当前是现有笔记生成的本地预览：尚未写入 mindmap_nodes 表，待导图后端接口接入后可刷新读取正式数据。" />
    <el-alert v-if="errorMessage" type="error" show-icon :closable="false"
      class="page-alert" :title="errorMessage" />
    <MindMapGraph v-if="treeData" :tree="treeData" />
    <el-empty v-else-if="!loading" description="暂无导图节点。请先完成课件整理，再生成思维导图。">
      <el-button :loading="building" @click="buildMindmap">尝试生成</el-button>
    </el-empty>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/utils/http'
import MindMapGraph from '@/components/MindMapGraph.vue'
import { normalizeMindmap, previewTreeFromResult } from '@/utils/mindmap'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const building = ref(false)
const courseName = ref('')
const treeData = ref(null)
const previewMode = ref(false)
const errorMessage = ref('')

// 后端导图 API 未合入时，使用已有的结构化笔记生成真实数据预览。
// 不调用模型、不伪造节点、不将这棵前端树冒充为已持久化的 mindmap_nodes。

async function loadMindmap() {
  loading.value = true
  errorMessage.value = ''
  previewMode.value = false
  treeData.value = null
  const id = route.params.id
  try {
    const data = await http.get(`/sessions/${id}/mindmap`)
    const tree = normalizeMindmap(data)
    if (tree) {
      treeData.value = data
      courseName.value = data?.course_name || ''
    } else {
      errorMessage.value = '服务端尚未生成导图节点，可点击“生成 / 重建导图”。'
    }
  } catch (error) {
    // 仅针对接口尚未交付（404）的情况尝试预览，认证失败/服务端错误不静默降级。
    if (error?.response?.status === 404) {
      try {
        const result = await http.get(`/sessions/${id}/result`)
        const preview = previewTreeFromResult(result)
        if (preview) {
          treeData.value = preview
          courseName.value = result.course_name || ''
          previewMode.value = true
        } else {
          errorMessage.value = '导图接口尚未接入，且该任务没有可用的结构化知识点。'
        }
      } catch (fallbackError) {
        errorMessage.value = fallbackError?.message || '无法获取该任务的整理结果。'
      }
    } else {
      errorMessage.value = error?.message || '导图加载失败，请稍后重试。'
    }
  } finally {
    loading.value = false
  }
}

async function buildMindmap() {
  building.value = true
  errorMessage.value = ''
  try {
    await http.post(`/sessions/${route.params.id}/mindmap/build`)
    ElMessage.success('导图构建请求已提交')
    await loadMindmap()
  } catch (error) {
    errorMessage.value = error?.response?.status === 404
      ? '后端生成接口尚未合入，请联系导图数据负责人；目前可使用已有笔记的本地预览。'
      : (error?.message || '导图生成失败')
  } finally {
    building.value = false
  }
}

watch(() => route.params.id, loadMindmap, { immediate: true })
</script>

<style scoped>
.mindmap-page { max-width: 1530px; padding: 22px 24px 46px; margin: 0 auto; }
.page-heading { display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 18px; margin-bottom: 22px; }
.page-heading h2 { margin: 16px 0 6px; display: flex; align-items: center; gap: 10px; color: #293b54; font-size: 25px; }
.page-heading p { margin: 0; color: #8895a9; font-size: 13px; }
.page-actions { display: flex; gap: 8px; }
.page-alert { margin-bottom: 16px; }
@media (max-width: 600px) { .mindmap-page { padding: 16px 10px 24px; } .page-heading h2 { font-size: 21px; } }
</style>
