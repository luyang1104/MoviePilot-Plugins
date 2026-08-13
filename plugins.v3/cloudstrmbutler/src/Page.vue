<template>
  <v-card class="task-page">
    <v-card-item class="page-header">
      <div>
        <v-card-title class="pa-0">同步工作台</v-card-title>
        <v-card-subtitle class="pa-0 mt-1">优先处理需要确认的同步事项。</v-card-subtitle>
      </div>
      <template #append>
        <v-btn
          icon="mdi-refresh"
          variant="text"
          :loading="loading"
          title="刷新状态"
          @click="load"
        />
      </template>
    </v-card-item>

    <v-divider />

    <v-card-text class="pa-4 pa-sm-6">
      <v-alert v-if="error" type="error" variant="tonal" closable class="mb-4" @click:close="error = ''">
        {{ error }}
      </v-alert>

      <section class="status-summary mb-5" :class="healthTone">
        <div class="status-mark">
          <v-icon :icon="healthIcon" size="28" />
        </div>
        <div class="status-copy">
          <div class="text-h6 font-weight-bold">{{ healthTitle }}</div>
          <div class="text-body-2 text-medium-emphasis mt-1">{{ healthDescription }}</div>
          <div class="status-meta mt-3">
            <span><v-icon icon="mdi-circle" size="8" class="mr-1" />{{ status.enabled ? '插件已启用' : '插件未启用' }}</span>
            <span><v-icon icon="mdi-clock-outline" size="16" class="mr-1" />{{ latestRun ? `最近运行 ${formatTime(latestRun.started_at)}` : '尚无运行记录' }}</span>
          </div>
        </div>
        <div v-if="status.reliable_engine" class="engine-chip">可靠同步引擎</div>
      </section>

      <section v-if="hasActionNeeded" class="mb-6">
        <div class="section-heading">
          <div>
            <h2>需要处理</h2>
            <p>先处理异常与待确认清理，避免问题在后台堆积。</p>
          </div>
          <v-chip color="warning" variant="tonal" size="small">{{ actionCount }} 项</v-chip>
        </div>

        <v-row dense>
          <v-col v-if="failures.length" cols="12" md="6">
            <v-sheet class="attention-card failure-card" border rounded="lg">
              <div class="attention-card__head">
                <div>
                  <div class="text-subtitle-1 font-weight-bold">同步失败</div>
                  <div class="text-body-2 text-medium-emphasis mt-1">{{ failures.length }} 个任务等待检查或重试</div>
                </div>
                <v-icon color="error" icon="mdi-alert-circle-outline" size="25" />
              </div>
              <div v-for="item in failures.slice(0, 2)" :key="item.id" class="attention-item">
                <div class="min-w-0">
                  <div class="path text-body-2">{{ item.path }}</div>
                  <div class="text-caption text-error mt-1">{{ item.error }}</div>
                  <div class="text-caption text-medium-emphasis mt-1">已尝试 {{ item.attempts }} 次 · {{ formatTime(item.updated_at) }}</div>
                </div>
                <v-btn
                  icon="mdi-replay"
                  variant="text"
                  size="small"
                  :loading="pending === `failure-${item.id}`"
                  title="重新加入同步队列"
                  @click="retry(item.id)"
                />
              </div>
              <v-btn v-if="failures.length > 2" variant="text" size="small" class="mt-2" @click="showFailures = !showFailures">
                {{ showFailures ? '收起失败列表' : `查看其余 ${failures.length - 2} 个失败` }}
              </v-btn>
            </v-sheet>
          </v-col>

          <v-col v-if="status.cleanup_batches.length" cols="12" md="6">
            <v-sheet class="attention-card cleanup-card" border rounded="lg">
              <div class="attention-card__head">
                <div>
                  <div class="text-subtitle-1 font-weight-bold">待确认清理</div>
                  <div class="text-body-2 text-medium-emphasis mt-1">删除前先核对输出路径与影响范围。</div>
                </div>
                <v-icon color="warning" icon="mdi-delete-clock-outline" size="25" />
              </div>
              <div v-for="batch in status.cleanup_batches.slice(0, 2)" :key="batch.batch_id" class="attention-item">
                <div class="min-w-0">
                  <div class="path text-body-2">{{ batch.monitor_root }}</div>
                  <div class="text-caption text-medium-emphasis mt-1">{{ batch.path_count }} 个生成文件 · 创建于 {{ formatTime(batch.created_at) }}</div>
                  <div class="text-caption text-medium-emphasis mt-1">{{ expirationLabel(batch.expires_at) }}</div>
                </div>
                <v-btn
                  color="warning"
                  variant="tonal"
                  size="small"
                  :loading="previewLoading === batch.batch_id"
                  @click="openCleanupPreview(batch.batch_id)"
                >预览</v-btn>
              </div>
            </v-sheet>
          </v-col>
        </v-row>

        <v-expand-transition>
          <v-table v-if="showFailures && failures.length > 2" density="comfortable" class="failure-table mt-3">
            <thead><tr><th>路径</th><th>原因</th><th>尝试次数</th><th>更新时间</th><th aria-label="操作"></th></tr></thead>
            <tbody>
              <tr v-for="item in failures.slice(2)" :key="item.id">
                <td class="path">{{ item.path }}</td><td>{{ item.error }}</td><td>{{ item.attempts }}</td><td>{{ formatTime(item.updated_at) }}</td>
                <td><v-btn icon="mdi-replay" size="small" variant="text" :loading="pending === `failure-${item.id}`" title="重新加入同步队列" @click="retry(item.id)" /></td>
              </tr>
            </tbody>
          </v-table>
        </v-expand-transition>
      </section>

      <section class="mb-6">
        <div class="section-heading">
          <div><h2>运行概览</h2><p>当前同步引擎的即时状态。</p></div>
        </div>
        <v-row dense>
          <v-col cols="6" sm="3"><div class="metric"><span>持久化队列</span><strong>{{ status.queued }}</strong><small>{{ status.queued ? '等待处理' : '无待处理任务' }}</small></div></v-col>
          <v-col cols="6" sm="3"><div class="metric"><span>内存队列</span><strong>{{ status.engine.memory_queued }}</strong><small>等待工作线程接收</small></div></v-col>
          <v-col cols="6" sm="3"><div class="metric"><span>正在处理</span><strong>{{ status.engine.inflight }}</strong><small>个同步任务</small></div></v-col>
          <v-col cols="6" sm="3"><div class="metric"><span>工作线程</span><strong>{{ status.engine.workers }}</strong><small>{{ status.reliable_engine ? '可靠引擎已启用' : '可靠引擎未启用' }}</small></div></v-col>
        </v-row>
      </section>

      <section>
        <div class="section-heading">
          <div><h2>最近运行</h2><p>保留最近 20 次同步结果，用于判断异常是否重复发生。</p></div>
        </div>
        <v-table density="comfortable" class="run-table">
          <thead><tr><th>开始时间</th><th>结果</th><th>排队</th><th>已处理</th><th>未变化</th><th>失败</th></tr></thead>
          <tbody>
            <tr v-for="run in status.recent_runs" :key="run.run_id">
              <td>{{ formatTime(run.started_at) }}</td>
              <td><v-chip :color="runColor(run.status)" size="x-small" variant="tonal">{{ runStatus(run.status) }}</v-chip></td>
              <td>{{ run.queued }}</td><td>{{ run.processed }}</td><td>{{ run.unchanged }}</td><td :class="{ 'text-error font-weight-bold': run.failed }">{{ run.failed }}</td>
            </tr>
            <tr v-if="!status.recent_runs.length"><td colspan="6" class="text-medium-emphasis text-center py-6">还没有同步记录。启用同步后，运行结果会出现在这里。</td></tr>
          </tbody>
        </v-table>
      </section>
    </v-card-text>
  </v-card>

  <v-dialog v-model="cleanupDialog" max-width="820" persistent>
    <v-card>
      <v-card-item>
        <div>
          <v-card-title class="pa-0">确认清理</v-card-title>
          <v-card-subtitle class="pa-0 mt-1">请先核对范围。确认后将删除下列已生成文件。</v-card-subtitle>
        </div>
        <template #append><v-btn icon="mdi-close" variant="text" title="关闭预览" :disabled="pending === `cleanup-${cleanupPreview?.batch_id}`" @click="closeCleanupPreview" /></template>
      </v-card-item>
      <v-divider />
      <v-card-text v-if="cleanupPreview" class="pa-4 pa-sm-6">
        <v-alert type="warning" variant="tonal" class="mb-5">
          将删除 <strong>{{ cleanupPreview.path_count }}</strong> 个 STRM 或旁车生成文件。不会删除云盘来源文件，也不会修改来源目录。
        </v-alert>
        <v-row dense class="mb-5">
          <v-col cols="12" sm="6"><div class="preview-summary"><span>监控目录</span><strong class="path">{{ cleanupPreview.monitor_root }}</strong><small>扫描发现来源文件已缺失</small></div></v-col>
          <v-col cols="12" sm="6"><div class="preview-summary"><span>批次状态</span><strong>{{ cleanupPreview.path_count }} 个文件</strong><small>{{ expirationLabel(cleanupPreview.expires_at) }}</small></div></v-col>
        </v-row>
        <div class="d-flex align-center flex-wrap ga-3 mb-3">
          <div class="text-subtitle-1 font-weight-bold">将要删除的文件</div>
          <v-spacer />
          <v-text-field v-model="cleanupSearch" prepend-inner-icon="mdi-magnify" label="筛选路径" variant="outlined" density="compact" hide-details style="max-width: 260px" />
        </div>
        <v-sheet border rounded="lg" class="cleanup-paths">
          <v-list density="compact" lines="one">
            <v-list-item v-for="path in filteredCleanupPaths" :key="path" :title="path" class="path-list-item" />
            <v-list-item v-if="!filteredCleanupPaths.length" title="没有匹配的文件路径" />
          </v-list>
        </v-sheet>
        <div v-if="filteredCleanupPaths.length < cleanupPreview.path_count" class="text-caption text-medium-emphasis mt-2">
          显示 {{ filteredCleanupPaths.length }} / {{ cleanupPreview.path_count }} 个文件。
        </div>
        <v-checkbox v-model="cleanupAcknowledged" color="warning" hide-details class="mt-5">
          <template #label><span class="text-body-2">我已核对目录和路径，了解此操作确认后不可撤回。</span></template>
        </v-checkbox>
      </v-card-text>
      <v-card-actions class="pa-4">
        <v-spacer />
        <v-btn variant="tonal" :disabled="pending === `cleanup-${cleanupPreview?.batch_id}`" @click="closeCleanupPreview">取消</v-btn>
        <v-btn color="error" variant="flat" :disabled="!cleanupAcknowledged" :loading="pending === `cleanup-${cleanupPreview?.batch_id}`" @click="confirmCleanup">确认清理</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <v-snackbar v-model="notice.visible" :color="notice.color" timeout="3500">{{ notice.text }}</v-snackbar>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

const props = defineProps({ api: { type: Object, default: () => ({}) } })
const loading = ref(false)
const pending = ref(null)
const error = ref('')
const failures = ref([])
const showFailures = ref(false)
const previewLoading = ref(null)
const cleanupDialog = ref(false)
const cleanupPreview = ref(null)
const cleanupSearch = ref('')
const cleanupAcknowledged = ref(false)
const notice = reactive({ visible: false, text: '', color: 'success' })
const status = reactive({ queued: 0, enabled: false, reliable_engine: false, engine: { memory_queued: 0, inflight: 0, workers: 0 }, recent_runs: [], cleanup_batches: [] })

const latestRun = computed(() => status.recent_runs[0] || null)
const actionCount = computed(() => failures.value.length + status.cleanup_batches.length)
const hasActionNeeded = computed(() => actionCount.value > 0)
const healthTitle = computed(() => {
  if (!status.enabled) return '同步尚未启用'
  if (actionCount.value) return `${actionCount.value} 项需要处理`
  if (!status.reliable_engine) return '同步正在运行'
  return '同步运行正常'
})
const healthDescription = computed(() => {
  if (!status.enabled) return '启用插件后，目录变化和同步结果会显示在这里。'
  if (failures.value.length) return '发现同步失败任务。请先查看原因，再重新加入同步队列。'
  if (status.cleanup_batches.length) return '有批次等待你核对后确认清理。'
  if (!status.reliable_engine) return '现有同步逻辑仍在工作；启用可靠同步引擎可获得队列与失败记录。'
  return '可靠同步引擎正在处理目录变化，没有任务积压。'
})
const healthIcon = computed(() => (status.enabled && !actionCount.value ? 'mdi-check-circle-outline' : actionCount.value ? 'mdi-alert-circle-outline' : 'mdi-information-outline'))
const healthTone = computed(() => (status.enabled && !actionCount.value ? 'is-healthy' : actionCount.value ? 'needs-attention' : 'is-neutral'))
const filteredCleanupPaths = computed(() => {
  const paths = cleanupPreview.value?.paths || []
  const term = cleanupSearch.value.trim().toLowerCase()
  return term ? paths.filter(path => path.toLowerCase().includes(term)) : paths
})

function formatTime(value) {
  return value ? new Date(Number(value) * 1000).toLocaleString() : '-'
}

function expirationLabel(value) {
  if (!value) return '无失效时间'
  const seconds = Math.max(0, Math.ceil((Number(value) * 1000 - Date.now()) / 1000))
  if (seconds < 3600) return `${Math.ceil(seconds / 60)} 分钟后失效`
  if (seconds < 86400) return `${Math.ceil(seconds / 3600)} 小时后失效`
  return `${Math.ceil(seconds / 86400)} 天后失效`
}

function runStatus(value) {
  return { completed: '完成', running: '运行中', failed: '异常' }[value] || value || '未知'
}

function runColor(value) {
  return { completed: 'success', running: 'info', failed: 'error' }[value] || 'secondary'
}

function showNotice(text, color = 'success') {
  notice.text = text
  notice.color = color
  notice.visible = true
}

async function load() {
  if (!props.api?.get) return
  loading.value = true
  error.value = ''
  try {
    const [statusResponse, failureResponse] = await Promise.all([
      props.api.get('plugin/CloudStrmButler/sync_status'),
      props.api.get('plugin/CloudStrmButler/sync_failures'),
    ])
    if (statusResponse?.code !== 0) throw new Error(statusResponse?.msg || '读取同步状态失败')
    if (failureResponse?.code !== 0) throw new Error(failureResponse?.msg || '读取失败任务失败')
    Object.assign(status, statusResponse.data || {})
    status.engine = { memory_queued: 0, inflight: 0, workers: 0, ...(status.engine || {}) }
    status.recent_runs = Array.isArray(status.recent_runs) ? status.recent_runs : []
    status.cleanup_batches = Array.isArray(status.cleanup_batches) ? status.cleanup_batches : []
    failures.value = failureResponse?.data?.items || []
  } catch (err) {
    error.value = err.message || '读取同步状态失败'
  } finally {
    loading.value = false
  }
}

async function retry(failureId) {
  pending.value = `failure-${failureId}`
  try {
    const response = await props.api.post('plugin/CloudStrmButler/sync_retry_failure', { failure_id: failureId })
    if (response?.code !== 0) throw new Error(response?.msg || '重试失败')
    showNotice(response?.msg || '已重新加入同步队列')
    await load()
  } catch (err) {
    error.value = err.message || '重试失败'
  } finally {
    pending.value = null
  }
}

async function openCleanupPreview(batchId) {
  if (!props.api?.get) return
  previewLoading.value = batchId
  error.value = ''
  try {
    const response = await props.api.get(`plugin/CloudStrmButler/sync_cleanup_preview?batch_id=${encodeURIComponent(batchId)}`)
    if (response?.code !== 0) throw new Error(response?.msg || '读取清理预览失败')
    cleanupPreview.value = response.data
    cleanupSearch.value = ''
    cleanupAcknowledged.value = false
    cleanupDialog.value = true
  } catch (err) {
    error.value = err.message || '读取清理预览失败'
  } finally {
    previewLoading.value = null
  }
}

function closeCleanupPreview() {
  cleanupDialog.value = false
  cleanupPreview.value = null
  cleanupSearch.value = ''
  cleanupAcknowledged.value = false
}

async function confirmCleanup() {
  const batchId = cleanupPreview.value?.batch_id
  if (!batchId || !cleanupAcknowledged.value) return
  pending.value = `cleanup-${batchId}`
  try {
    const response = await props.api.post('plugin/CloudStrmButler/sync_confirm_cleanup', { batch_id: batchId })
    if (response?.code !== 0) throw new Error(response?.msg || '清理失败')
    closeCleanupPreview()
    showNotice(response?.msg || '已清理生成文件')
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
.task-page { overflow: hidden; }
.page-header :deep(.v-card-title) { font-size: 22px; letter-spacing: 0; }
.status-summary { display: flex; align-items: flex-start; gap: 16px; padding: 20px; border: 1px solid; border-radius: 8px; }
.status-summary.is-healthy { background: #f2faf5; border-color: #b7dfc8; color: #246946; }
.status-summary.needs-attention { background: #fff8f1; border-color: #f0cead; color: #955035; }
.status-summary.is-neutral { background: #f4f8fb; border-color: #d7e3ec; color: #365d76; }
.status-mark { width: 48px; height: 48px; border-radius: 50%; display: grid; place-items: center; flex: 0 0 auto; background: currentColor; color: #fff; }
.status-copy { min-width: 0; color: rgb(var(--v-theme-on-surface)); }
.status-meta { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: rgb(var(--v-theme-on-surface-variant)); }
.status-meta span { display: inline-flex; align-items: center; }
.is-healthy .status-meta :deep(.v-icon) { color: #369261; }.needs-attention .status-meta :deep(.v-icon) { color: #ce713f; }.is-neutral .status-meta :deep(.v-icon) { color: #47728d; }
.engine-chip { margin-left: auto; padding: 6px 10px; border-radius: 4px; background: rgba(43, 110, 78, .11); color: #2f7652; font-size: 12px; font-weight: 700; white-space: nowrap; }
.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 12px; }.section-heading h2 { margin: 0; font-size: 17px; line-height: 1.4; letter-spacing: 0; }.section-heading p { margin: 4px 0 0; color: rgb(var(--v-theme-on-surface-variant)); font-size: 13px; }
.attention-card { min-height: 190px; padding: 18px; border-radius: 8px !important; }.failure-card { border-color: #ebc7b5 !important; }.cleanup-card { border-color: #ead6a9 !important; }.attention-card__head { display: flex; justify-content: space-between; gap: 12px; padding-bottom: 12px; border-bottom: 1px solid rgba(var(--v-border-color), .55); }.attention-item { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding: 12px 0 0; }.attention-item + .attention-item { margin-top: 10px; border-top: 1px solid rgba(var(--v-border-color), .35); }.min-w-0 { min-width: 0; }.path { max-width: 100%; overflow-wrap: anywhere; word-break: break-word; }.failure-table, .run-table { border: 1px solid rgba(var(--v-border-color), .5); border-radius: 8px; overflow: hidden; }.metric { min-height: 128px; padding: 16px; border: 1px solid rgba(var(--v-border-color), .5); border-radius: 8px; display: flex; flex-direction: column; background: rgb(var(--v-theme-surface)); }.metric span { color: rgb(var(--v-theme-on-surface-variant)); font-size: 12px; }.metric strong { margin-top: 10px; font-size: 29px; line-height: 1; }.metric small { margin-top: auto; color: rgb(var(--v-theme-on-surface-variant)); font-size: 12px; }.preview-summary { min-height: 98px; padding: 14px; border: 1px solid rgba(var(--v-border-color), .5); border-radius: 8px; display: flex; flex-direction: column; gap: 6px; background: rgba(var(--v-theme-surface-variant), .18); }.preview-summary > span, .preview-summary small { color: rgb(var(--v-theme-on-surface-variant)); font-size: 12px; }.preview-summary strong { font-size: 14px; }.cleanup-paths { max-height: 250px; overflow: auto; }.path-list-item :deep(.v-list-item-title) { overflow-wrap: anywhere; white-space: normal; font-size: 13px; }
@media (max-width: 600px) { .status-summary { padding: 16px; }.status-mark { width: 40px; height: 40px; }.engine-chip { display: none; }.status-meta { gap: 8px; }.section-heading { gap: 8px; }.metric { min-height: 112px; padding: 14px; }.run-table :deep(th), .run-table :deep(td) { padding-inline: 10px; }.run-table :deep(th:nth-child(3)), .run-table :deep(td:nth-child(3)), .run-table :deep(th:nth-child(5)), .run-table :deep(td:nth-child(5)) { display: none; } }
</style>
