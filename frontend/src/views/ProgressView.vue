<template>
  <div style="padding: 40px; max-width: 800px; margin: 0 auto;">
    <h2>{{ title }}</h2>
    <p style="color: #666;">整理通常需要 30~120 秒（课件越大越久），请不要关闭页面</p>

    <el-progress :percentage="percent" :status="progressStatus" style="margin-top: 24px;" />
    <p style="text-align: center; margin-top: 12px; color: #606266;">{{ stageText }}</p>

    <el-alert
      v-if="errorMessage"
      title="任务失败"
      :description="errorMessage"
      type="error"
      show-icon
      style="margin-top: 24px;"
    />

    <el-alert
      v-if="timeoutMessage"
      title="等待超时"
      :description="timeoutMessage"
      type="warning"
      show-icon
      style="margin-top: 24px;"
    />

    <div v-if="finished" style="margin-top: 24px; text-align: center;">
      <el-button @click="router.push('/upload')">重新上传</el-button>
      <el-button type="primary" @click="router.push('/sessions')">查看历史任务</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/utils/http'

const route = useRoute()
const router = useRouter()

const percent = ref(0)
const stageText = ref('正在提交任务…')
const backendStatus = ref('pending')
const errorMessage = ref('')
const timeoutMessage = ref('')

// 轮询间隔与上限：1.5 秒一次，最多等 6 分钟（再久多半是卡住了）
const POLL_INTERVAL = 1500
const MAX_WAIT_MS = 6 * 60 * 1000

let timer = null
let startedAt = 0
let stopped = false

const title = computed(() => {
  if (backendStatus.value === 'failed') return '整理失败'
  if (backendStatus.value === 'success' || backendStatus.value === 'partial') return '整理已完成'
  return '正在整理笔记…'
})

const progressStatus = computed(() => {
  if (backendStatus.value === 'failed') return 'exception'
  if (backendStatus.value === 'success' || backendStatus.value === 'partial') return 'success'
  return ''
})

const finished = computed(
  () => ['success', 'partial', 'failed'].includes(backendStatus.value) || !!timeoutMessage.value
)

async function tick() {
  if (stopped) return
  try {
    // 拦截器已剥掉外层包络，这里直接拿到 SessionOut
    const session = await http.get(`/sessions/${route.params.id}`)
    if (!session) return

    backendStatus.value = session.status || 'pending'
    percent.value = Number(session.progress || 0)
    stageText.value = session.stage_message || '处理中…'

    if (session.status === 'failed') {
      errorMessage.value = session.error_message || '未知错误，请到服务器日志查看详细原因'
      stop()
      return
    }

    if (session.status === 'success' || session.status === 'partial') {
      percent.value = 100
      stageText.value = session.status === 'partial'
        ? '整理完成（部分内容有告警，结果页会显示）'
        : '整理完成，正在打开结果…'
      stop()
      // 稍等一下让用户看到 100%，再跳到结果页
      setTimeout(() => router.push(`/sessions/${route.params.id}/result`), 800)
      return
    }

    if (Date.now() - startedAt > MAX_WAIT_MS) {
      timeoutMessage.value = '等待超过 6 分钟仍未完成。任务可能仍在后台运行，可以先到「历史任务」查看；'
        + '若长时间无进展，请检查服务器日志与模型密钥配置。'
      stop()
    }
  } catch (e) {
    // 单次请求失败（网络抖动、服务重启）不应中断整体等待，继续下一轮
    console.warn('轮询任务状态失败，稍后重试：', e)
    stageText.value = '状态获取失败，正在重试…'
  }
}

function stop() {
  stopped = true
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

onMounted(() => {
  startedAt = Date.now()
  tick()
  timer = setInterval(tick, POLL_INTERVAL)
})

onUnmounted(stop)
</script>
