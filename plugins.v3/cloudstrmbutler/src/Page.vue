<template>
  <v-card class="task-page">
    <v-card-item>
      <v-card-title>云盘 Strm 小管家</v-card-title>
      <template #append>
        <v-btn icon="mdi-refresh" variant="text" :loading="loading" title="刷新状态" @click="load" />
      </template>
    </v-card-item>
    <v-divider />
    <v-card-text>
      <v-alert v-if="error" type="error" variant="tonal" class="mb-3">{{ error }}</v-alert>
      <v-row dense class="mb-4">
        <v-col cols="6" sm="3"><div class="metric"><span>持久化队列</span><strong>{{ status.queued }}</strong></div></v-col>
        <v-col cols="6" sm="3"><div class="metric"><span>内存队列</span><strong>{{ status.engine.memory_queued }}</strong></div></v-col>
        <v-col cols="6" sm="3"><div class="metric"><span>处理中</span><strong>{{ status.engine.inflight }}</strong></div></v-col>
        <v-col cols="6" sm="3"><div class="metric"><span>工作线程</span><strong>{{ status.engine.workers }}</strong></div></v-col>
      </v-row>

      <v-alert v-if="!status.reliable_engine" type="info" variant="tonal" class="mb-4">
        可靠同步引擎尚未启用。现有同步逻辑仍正常工作。
      </v-alert>

      <div class="section-title">最近任务</div>
      <v-table density="compact" class="mb-5">
        <thead><tr><th>开始时间</th><th>状态</th><th>排队</th><th>已处理</th><th>未变化</th><th>失败</th></tr></thead>
        <tbody>
          <tr v-for="run in status.recent_runs" :key="run.run_id">
            <td>{{ formatTime(run.started_at) }}</td><td>{{ run.status }}</td><td>{{ run.queued }}</td><td>{{ run.processed }}</td><td>{{ run.unchanged }}</td><td>{{ run.failed }}</td>
          </tr>
          <tr v-if="!status.recent_runs.length"><td colspan="6" class="text-medium-emphasis">暂无任务记录</td></tr>
        </tbody>
      </v-table>

      <div class="section-title">同步失败</div>
      <v-table density="compact" class="mb-5">
        <thead><tr><th>路径</th><th>错误</th><th>次数</th><th>更新时间</th><th></th></tr></thead>
        <tbody>
          <tr v-for="item in failures" :key="item.id">
            <td class="path">{{ item.path }}</td><td>{{ item.error }}</td><td>{{ item.attempts }}</td><td>{{ formatTime(item.updated_at) }}</td>
            <td><v-btn icon="mdi-replay" size="small" variant="text" title="重试" :loading="pending === item.id" @click="retry(item.id)" /></td>
          </tr>
          <tr v-if="!failures.length"><td colspan="5" class="text-medium-emphasis">没有未解决的失败任务</td></tr>
        </tbody>
      </v-table>

      <div class="section-title">待确认清理</div>
      <v-table density="compact">
        <thead><tr><th>监控目录</th><th>文件数</th><th>创建时间</th><th></th></tr></thead>
        <tbody>
          <tr v-for="batch in status.cleanup_batches" :key="batch.batch_id">
            <td class="path">{{ batch.monitor_root }}</td><td>{{ batch.path_count }}</td><td>{{ formatTime(batch.created_at) }}</td>
            <td><v-btn color="warning" variant="tonal" size="small" :loading="pending === batch.batch_id" @click="confirmCleanup(batch.batch_id)">确认清理</v-btn></td>
          </tr>
          <tr v-if="!status.cleanup_batches.length"><td colspan="4" class="text-medium-emphasis">没有待确认的清理批次</td></tr>
        </tbody>
      </v-table>
    </v-card-text>
  </v-card>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'

const props = defineProps({ api: { type: Object, default: () => ({}) } })
const loading = ref(false)
const pending = ref(null)
const error = ref('')
const failures = ref([])
const status = reactive({ queued: 0, reliable_engine: false, engine: { memory_queued: 0, inflight: 0, workers: 0 }, recent_runs: [], cleanup_batches: [] })

function formatTime(value) {
  return value ? new Date(Number(value) * 1000).toLocaleString() : '-'
}

async function load() {
  if (!props.api?.get) return
  loading.value = true
  error.value = ''
  try {
    const [statusResponse, failureResponse] = await Promise.all([
      props.api.get('plugin/cloudstrmbutler/sync_status'),
      props.api.get('plugin/cloudstrmbutler/sync_failures'),
    ])
    if (statusResponse?.code !== 0) throw new Error(statusResponse?.msg || '读取状态失败')
    Object.assign(status, statusResponse.data || {})
    failures.value = failureResponse?.data?.items || []
  } catch (err) {
    error.value = err.message || '读取状态失败'
  } finally {
    loading.value = false
  }
}

async function retry(failureId) {
  pending.value = failureId
  try {
    const response = await props.api.post('plugin/cloudstrmbutler/sync_retry_failure', { failure_id: failureId })
    if (response?.code !== 0) throw new Error(response?.msg || '重试失败')
    await load()
  } catch (err) {
    error.value = err.message || '重试失败'
  } finally {
    pending.value = null
  }
}

async function confirmCleanup(batchId) {
  pending.value = batchId
  try {
    const response = await props.api.post('plugin/cloudstrmbutler/sync_confirm_cleanup', { batch_id: batchId })
    if (response?.code !== 0) throw new Error(response?.msg || '清理失败')
    await load()
  } catch (err) {
    error.value = err.message || '清理失败'
  } finally {
    pending.value = null
  }
}

onMounted(load)
</script>

<style scoped>
.metric { border: 1px solid rgba(var(--v-border-color), .45); padding: 10px; min-height: 70px; display: flex; flex-direction: column; justify-content: space-between; }
.metric span { color: rgba(var(--v-theme-on-surface), .65); font-size: 12px; }
.metric strong { font-size: 24px; line-height: 1; }
.section-title { font-size: 16px; font-weight: 600; margin: 12px 0 8px; }
.path { max-width: 340px; overflow-wrap: anywhere; }
</style>
