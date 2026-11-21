<template>
  <div style="padding: 20px;">
    <div style="display: flex; align-items: center; gap: 12px;">
      <h2 style="margin: 0;">历史任务</h2>
      <el-button size="small" :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="errorMessage"
      :title="errorMessage"
      type="error"
      show-icon
      style="margin-top: 16px;"
    />

    <el-table :data="sessions" style="width: 100%; margin-top: 20px;" v-loading="loading">
      <!-- 后端字段是 session_id，不是 id；这里用 prop 直取会空白 -->
      <el-table-column label="任务" width="90">
        <template #default="{ row }">#{{ row.session_id }}</template>
      </el-table-column>
      <el-table-column prop="course_name" label="课程" min-width="150" />
      <el-table-column prop="source_file" label="材料" min-width="180" show-overflow-tooltip />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="进度" width="100">
        <template #default="{ row }">{{ row.progress || 0 }}%</template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180" />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="['pending', 'running'].includes(row.status)"
            size="small"
            @click="router.push(`/sessions/${row.session_id}/progress`)"
          >查看进度</el-button>
          <el-button
            v-else
            size="small"
            type="primary"
            @click="router.push(`/sessions/${row.session_id}/result`)"
          >查看结果</el-button>
          <el-button
            v-if="['success', 'partial'].includes(row.status)"
            size="small"
            type="warning"
            plain
            @click="router.push(`/upload?append=${row.session_id}`)"
          >补充材料</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty
      v-if="!loading && !errorMessage && sessions.length === 0"
      description="还没有整理记录，先去上传一份课件吧"
      style="margin-top: 50px;"
    >
      <el-button type="primary" @click="router.push('/upload')">上传课件</el-button>
    </el-empty>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import http from '@/utils/http'

const router = useRouter()
const sessions = ref([])
const loading = ref(true)
const errorMessage = ref('')

const STATUS_TEXT = {
  pending: '等待中',
  running: '整理中',
  success: '已完成',
  partial: '部分完成',
  failed: '失败'
}
const STATUS_TYPE = {
  pending: 'info',
  running: 'warning',
  success: 'success',
  partial: 'warning',
  failed: 'danger'
}

function statusText(s) {
  return STATUS_TEXT[s] || s || '未知'
}
function statusType(s) {
  return STATUS_TYPE[s] || 'info'
}

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    // 拦截器已剥掉外层包络，直接得到 SessionOut 数组
    sessions.value = (await http.get('/sessions')) || []
  } catch (e) {
    // 不要塞假数据：如实告知失败，否则团队会误以为接口正常
    errorMessage.value = e?.message || '历史任务加载失败，请稍后重试'
    sessions.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
/* 毛玻璃表格：表头与行全部透明，让全局渐变透出来 */
:deep(.el-table) {
  backdrop-filter: blur(15px);
  -webkit-backdrop-filter: blur(15px);
  border: 1px solid rgba(255, 255, 255, 0.4);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.05);
  --el-table-bg-color: transparent !important;
  --el-table-tr-bg-color: transparent !important;
  --el-table-header-bg-color: transparent !important;
  background-color: rgba(255, 255, 255, 0.15) !important;
}
:deep(.el-table__inner-wrapper),
:deep(.el-table tr),
:deep(.el-table th.el-table__cell),
:deep(.el-table td.el-table__cell) {
  background-color: transparent !important;
}
:deep(.el-table th.el-table__cell) {
  color: #333;
  border-bottom: 1px solid rgba(0, 0, 0, 0.1) !important;
}
:deep(.el-table td.el-table__cell) {
  border-bottom: 1px solid rgba(0, 0, 0, 0.05) !important;
}
</style>
