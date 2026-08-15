<template>
  <div class="cloudstrm-shell v-theme--dark" style="color-scheme: dark">
    <div class="shell-frame">
      <header class="shell-header">
        <div class="shell-header-top">
          <div class="brand-lockup">
            <div class="brand-mark" aria-hidden="true">
              <v-icon size="21">mdi-cloud-sync-outline</v-icon>
            </div>
            <div class="brand-copy">
              <div class="brand-title">云盘 STRM 小管家</div>
              <div class="brand-subtitle">STRM 同步与目录管理</div>
            </div>
            <span class="brand-version">v{{ version }}</span>
          </div>
          <div class="header-actions">
            <div class="runtime-indicator" :class="{ 'is-active': runtimeActive }">
              <span class="runtime-dot" aria-hidden="true"></span>
              <span>{{ runtimeLabel }}</span>
            </div>
            <v-btn
              class="header-refresh"
              icon="mdi-refresh"
              variant="text"
              size="small"
              :loading="loading"
              title="刷新状态"
              aria-label="刷新状态"
              @click="load"
            />
          </div>
        </div>
        <nav class="tab-bar" role="tablist" aria-label="插件视图">
          <button
            class="tab-button"
            :class="{ 'is-active': activeTab === 'dashboard' }"
            type="button"
            role="tab"
            :aria-selected="activeTab === 'dashboard'"
            @click="activeTab = 'dashboard'"
          >
            <v-icon size="17">mdi-chart-box-outline</v-icon>
            <span>运行状态</span>
          </button>
          <button
            class="tab-button"
            :class="{ 'is-active': activeTab === 'config' }"
            type="button"
            role="tab"
            :aria-selected="activeTab === 'config'"
            @click="activeTab = 'config'"
          >
            <v-icon size="17">mdi-tune-variant</v-icon>
            <span>插件配置</span>
          </button>
        </nav>
      </header>
      <div class="shell-main">
        <div class="shell-divider" aria-hidden="true"></div>

        <main class="shell-content">
        <v-alert v-if="error" type="error" variant="tonal" class="shell-alert" closable @click:close="error = ''">
          {{ error }}
        </v-alert>

        <section v-show="activeTab === 'dashboard'" class="dashboard-view" aria-labelledby="dashboard-title">
        <div class="page-intro">
          <div>
            <span class="eyebrow">OPERATIONS</span>
            <h1 id="dashboard-title">同步工作台</h1>
            <p>查看同步健康度，并优先处理需要你确认的事项。</p>
          </div>
          <div class="intro-meta">
            <span class="meta-label">最后刷新</span>
            <strong>{{ lastUpdatedLabel }}</strong>
          </div>
          <div class="intro-actions">
            <v-btn
              color="primary"
              variant="flat"
              prepend-icon="mdi-play-circle-outline"
              :loading="fullScanPending"
              :disabled="fullScanPending || status.scan_running || status.command_running || status.scan_progress.running"
              @click="startFullScan"
            >
              执行一次全量处理
            </v-btn>
            <span>有效规则全部扫描 · 已存在跳过 · 缺失才生成</span>
          </div>
        </div>

        <section class="runtime-banner" :class="{ 'is-active': runtimeActive }" aria-label="同步引擎状态">
          <div class="banner-icon" aria-hidden="true">
            <v-icon>{{ runtimeActive ? 'mdi-pulse' : 'mdi-pause-circle-outline' }}</v-icon>
          </div>
          <div class="banner-copy">
            <strong>{{ runtimeTitle }}</strong>
            <span>{{ runtimeDescription }}</span>
          </div>
          <v-chip size="small" :color="runtimeActive ? 'success' : 'secondary'" variant="tonal">
            {{ runtimeActive ? '处理中' : (status.service_state === 'pending_recovery' ? '待恢复' : '待机') }}
          </v-chip>
        </section>

        <section class="content-section engine-metrics-section" aria-labelledby="engine-metrics-title">
          <div class="section-heading section-heading--compact">
            <div>
              <h2 id="engine-metrics-title">可靠同步引擎指标</h2>
              <p>持久化队列、内存队列、处理中、工作线程作为现有引擎指标保留。</p>
            </div>
          </div>

          <div class="metric-grid" aria-label="可靠同步引擎指标">
          <article class="metric-tile">
            <div class="metric-heading">
              <span>持久化队列</span>
              <v-icon size="18">mdi-database-outline</v-icon>
            </div>
            <strong>{{ status.queued }}</strong>
            <span class="metric-caption">{{ status.queue_active ? '等待可靠引擎处理的任务' : (status.pending_jobs ? '引擎未运行，任务会保留待恢复' : '可靠任务队列当前为空') }}</span>
          </article>
          <article class="metric-tile">
            <div class="metric-heading">
              <span>内存队列</span>
              <v-icon size="18">mdi-memory</v-icon>
            </div>
            <strong>{{ status.engine.memory_queued }}</strong>
            <span class="metric-caption">已载入可靠引擎、等待执行的内容</span>
          </article>
          <article class="metric-tile metric-tile--accent">
            <div class="metric-heading">
              <span>处理中</span>
              <v-icon size="18">mdi-sync</v-icon>
            </div>
            <strong>{{ status.engine.inflight }}</strong>
            <span class="metric-caption">可靠引擎当前正在处理的内容</span>
          </article>
          <article class="metric-tile">
            <div class="metric-heading">
              <span>工作线程</span>
              <v-icon size="18">mdi-lan-connect</v-icon>
            </div>
            <strong>{{ status.engine.workers }}</strong>
            <span class="metric-caption">可靠引擎已启动的并发线程</span>
          </article>
          </div>
        </section>

        <section class="content-section processing-overview-section" aria-labelledby="processing-overview-title">
          <div class="section-heading section-heading--compact">
            <div>
              <h2 id="processing-overview-title">处理概览</h2>
              <p>按源目录核对媒体、非媒体文件和字幕的处理结果。</p>
            </div>
            <span class="overview-refresh-state" :class="{ 'is-ready': processingOverview.record_ready }">
              {{ processingOverview.ready ? `已核对 ${formatTime(processingOverview.last_checked_at)}` : processingOverview.record_ready ? '已有记录，后台核对中' : '正在核对源目录' }}
            </span>
          </div>

          <div class="processing-overview-grid">
            <article class="processing-overview-card processing-overview-card--strm">
              <div class="overview-card-heading">
                <span>STRM 生成记录</span>
                <v-icon size="18">mdi-file-link-outline</v-icon>
              </div>
              <div class="overview-card-body">
                <div class="overview-value-group">
                  <span>媒体总数</span>
                  <strong>{{ processingOverview.media_total }}</strong>
                </div>
                <div class="overview-value-group">
                  <span>已生成 STRM</span>
                  <strong>{{ processingOverview.strm_total }}</strong>
                </div>
                <div class="overview-consistency" :class="overviewConsistencyTone">
                  <v-icon size="15">{{ processingOverview.media_strm_consistent ? 'mdi-check-circle-outline' : 'mdi-alert-circle-outline' }}</v-icon>
                  <strong>{{ overviewConsistencyLabel }}</strong>
                  <span v-if="processingOverview.record_ready && !processingOverview.media_strm_consistent">少 {{ Math.max(0, Number(processingOverview.media_total || 0) - Number(processingOverview.strm_total || 0)) }} 个 STRM</span>
                </div>
              </div>
              <span class="overview-card-note">数量核对只比较媒体总数与已生成 STRM，不展开文件记录。</span>
            </article>

            <article class="processing-overview-card processing-overview-card--side">
              <div class="overview-card-heading">
                <span>非媒体与字幕</span>
                <span class="overview-side-caption">总数 / 已完成</span>
              </div>
              <div class="overview-stat-row">
                <div class="overview-stat-label">
                  <v-icon size="17">mdi-file-document-outline</v-icon>
                  <span>非媒体文件</span>
                </div>
                <strong>{{ processingOverview.non_media_total }}</strong>
                <strong class="overview-stat-completed">已完成 {{ processingOverview.non_media_completed }}</strong>
                <v-progress-linear
                  :model-value="completionPercent(processingOverview.non_media_total, processingOverview.non_media_completed)"
                  color="success"
                  bg-color="secondary"
                  height="6"
                  rounded
                />
              </div>
              <div class="overview-stat-row overview-stat-row--subtitle">
                <div class="overview-stat-label">
                  <v-icon size="17">mdi-subtitles-outline</v-icon>
                  <span>字幕文件</span>
                </div>
                <strong>{{ processingOverview.subtitle_total }}</strong>
                <strong class="overview-stat-completed overview-stat-completed--subtitle">已完成 {{ processingOverview.subtitle_completed }}</strong>
                <v-progress-linear
                  :model-value="completionPercent(processingOverview.subtitle_total, processingOverview.subtitle_completed)"
                  color="warning"
                  bg-color="secondary"
                  height="6"
                  rounded
                />
              </div>
            </article>
          </div>
        </section>

        <section class="content-section full-scan-section" aria-labelledby="full-scan-title">
          <div class="section-heading section-heading--compact">
            <div>
              <h2 id="full-scan-title">一次全量处理</h2>
              <p>扫描所有有效规则，已存在跳过，不存在才生成。</p>
            </div>
            <span class="status-chip" :class="fullScanProgress.running ? 'status-chip--active' : fullScanProgress.failed ? 'status-chip--danger' : fullScanProgress.run_id ? 'status-chip--success' : 'status-chip--muted'">
              {{ fullScanProgressPhaseLabel }}
            </span>
          </div>

          <div class="command-progress-frame full-scan-frame">
            <div class="full-scan-toolbar">
              <span class="scan-state" :class="fullScanProgress.running ? 'scan-state--running' : fullScanProgress.run_id ? 'scan-state--done' : 'scan-state--idle'">
                <span class="scan-state-dot" aria-hidden="true"></span>
                {{ fullScanProgress.running ? '扫描中' : fullScanProgress.run_id ? '已完成' : '尚未执行' }}
              </span>
              <span class="full-scan-label">手动全量处理 <span aria-hidden="true">|</span> 刷新状态</span>
              <span class="full-scan-state">{{ fullScanProgressPhaseLabel }}</span>
            </div>

            <div class="full-scan-details">
              <div class="full-scan-detail">
                <span>当前规则</span>
                <strong>{{ fullScanProgress.current_rule || '暂无' }}</strong>
              </div>
              <div class="full-scan-detail full-scan-detail--path">
                <span>当前文件</span>
                <strong :title="fullScanProgress.current_path">{{ fullScanProgress.current_path || '暂无，点击上方按钮开始全量处理' }}</strong>
              </div>
            </div>

            <v-progress-linear
              :model-value="fullScanProgressPercent"
              :indeterminate="fullScanProgress.running && fullScanProgress.total === 0"
              color="primary"
              bg-color="secondary"
              height="7"
              rounded
            />

            <div class="full-scan-footer">
              <span>已处理 {{ fullScanProgress.processed || 0 }} / {{ fullScanProgress.total || 0 }}</span>
              <span>最近进度 {{ formatTime(fullScanProgress.last_progress_at) }}</span>
              <span>{{ fullScanProgress.running ? '运行中自动禁用重复执行' : '已存在内容会自动跳过' }}</span>
            </div>

            <div v-if="fullScanProgress.stalled" class="stalled-warning">
              <v-icon size="18">mdi-alert-outline</v-icon>
              <span>超过 {{ formatDuration(fullScanProgress.stalled_seconds) }} 没有新的完成记录，可能正在等待 NAS 文件 I/O。</span>
            </div>

            <div class="result-summary-heading">
              <strong>处理结果</strong>
              <span v-if="fullScanProgress.failed" class="danger-number">失败 {{ fullScanProgress.failed }} 个</span>
            </div>
            <div class="result-category-grid">
              <article v-for="category in resultCategories" :key="category.key" class="result-category" :class="'result-category--' + category.tone">
                <span>{{ category.label }}</span>
                <strong>{{ fullScanProgress.result_counts?.[category.key] || 0 }}</strong>
              </article>
            </div>
          </div>
        </section>

        <section v-if="commandProgressHasData" class="content-section command-progress-section" aria-labelledby="command-progress-title">
          <div class="section-heading section-heading--compact">
            <div>
              <h2 id="command-progress-title">手动 /strm 扫描</h2>
              <p>{{ commandProgress.running ? '手动扫描正在独立执行，进度不会计入可靠同步引擎的四项指标。' : '最近一次手动扫描的处理结果。' }}</p>
            </div>
            <span class="status-chip" :class="commandProgress.running ? 'status-chip--active' : 'status-chip--success'">{{ commandProgressPhaseLabel }}</span>
          </div>

          <div class="command-progress-frame">
            <div class="command-progress-top">
              <div class="command-progress-copy">
                <span class="metric-caption">{{ commandProgress.label || '手动 /strm' }}</span>
                <strong>{{ commandProgressCompleted }} / {{ commandProgress.total }}</strong>
                <span>{{ commandProgress.running ? '已完成文件 / 已发现文件' : '本次扫描已处理文件 / 总文件数' }}</span>
              </div>
              <v-icon size="25" :color="commandProgress.stalled ? 'warning' : commandProgress.running ? 'success' : 'secondary'">{{ commandProgress.stalled ? 'mdi-timer-alert-outline' : commandProgress.running ? 'mdi-progress-clock' : 'mdi-check-circle-outline' }}</v-icon>
            </div>
            <v-progress-linear
              :model-value="commandProgressPercent"
              :indeterminate="commandProgress.running && commandProgress.total === 0"
              color="primary"
              bg-color="secondary"
              height="7"
              rounded
            />

            <div class="command-detail-grid">
              <div class="command-detail">
                <span>阶段</span>
                <strong>{{ commandProgressPhaseLabel }}</strong>
              </div>
              <div class="command-detail command-detail--path">
                <span>当前文件</span>
                <strong :title="commandProgress.current_path">{{ commandProgress.current_path || '暂无' }}</strong>
              </div>
              <div class="command-detail">
                <span>最后进度</span>
                <strong>{{ formatTime(commandProgress.last_progress_at) }}</strong>
              </div>
            </div>

            <div v-if="commandProgress.stalled" class="stalled-warning">
              <v-icon size="18">mdi-alert-outline</v-icon>
              <span>超过 {{ formatDuration(commandProgress.stalled_seconds) }} 没有新的完成记录，可能正在等待 NAS 文件 I/O；当前文件仍是上面显示的路径。</span>
            </div>

            <div class="result-summary-heading">
              <strong>处理结果</strong>
              <span v-if="commandProgress.errors.length" class="danger-number">失败示例 {{ commandProgress.errors.length }} 条</span>
            </div>
            <div class="result-category-grid">
              <article v-for="category in resultCategories" :key="category.key" class="result-category" :class="`result-category--${category.tone}`">
                <span>{{ category.label }}</span>
                <strong>{{ commandProgress.result_counts[category.key] || 0 }}</strong>
              </article>
            </div>

            <ul v-if="commandProgress.errors.length" class="command-errors">
              <li v-for="item in commandProgress.errors" :key="item">{{ item }}</li>
            </ul>
          </div>
        </section>

        <section class="content-section" aria-labelledby="recent-runs-title">
          <div class="section-heading">
            <div>
              <h2 id="recent-runs-title">最近任务</h2>
              <p>最近一次全量扫描与实时同步的处理摘要。</p>
            </div>
            <v-btn
              icon="mdi-refresh"
              variant="tonal"
              size="small"
              :loading="loading"
              title="刷新最近任务"
              aria-label="刷新最近任务"
              @click="load"
            />
          </div>

          <div class="table-frame recent-task-table">
            <v-table density="comfortable" class="status-table">
              <thead>
                <tr>
                  <th>状态</th>
                  <th>排队</th>
                  <th>已处理</th>
                  <th>处理结果</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="run in status.recent_runs" :key="run.run_id">
                  <td><span class="status-chip" :class="statusTone(run.status)">{{ displayStatus(run.status) }}</span></td>
                  <td>{{ run.queued ?? 0 }}</td>
                  <td>{{ run.processed ?? 0 }}</td>
                  <td class="result-cell">
                    <template v-if="resultItems(run).length">
                      <span v-for="item in resultItems(run)" :key="item.key" class="result-inline" :class="`result-inline--${item.tone}`">{{ item.label }} {{ item.count }}</span>
                    </template>
                    <span v-else class="muted-value">-</span>
                  </td>
                </tr>
                <tr v-if="!status.recent_runs.length">
                  <td colspan="4" class="empty-row">暂无任务记录</td>
                </tr>
              </tbody>
            </v-table>
          </div>
        </section>

        <div class="dashboard-columns">
          <section class="content-section" aria-labelledby="failures-title">
            <div class="section-heading section-heading--compact">
              <div>
                <h2 id="failures-title">同步失败记录</h2>
                <p>修复原因后，可选择多个任务重新加入队列。</p>
              </div>
              <div class="failure-actions">
                <span class="section-count" :class="{ 'has-items': failures.length }">{{ failures.length }}</span>
                <v-btn
                  size="small"
                  variant="tonal"
                  :prepend-icon="allFailuresSelected ? 'mdi-checkbox-multiple-blank-outline' : 'mdi-checkbox-multiple-marked-outline'"
                  :disabled="!failures.length || pending !== null"
                  @click="toggleAllFailures"
                >
                  {{ allFailuresSelected ? '取消全选' : '全选' }}
                </v-btn>
                <v-btn
                  size="small"
                  color="primary"
                  variant="flat"
                  prepend-icon="mdi-replay"
                  :loading="pending === 'failure-batch'"
                  :disabled="!selectedFailureIds.length || pending !== null"
                  @click="retrySelected"
                >
                  批量重试 {{ selectedFailureIds.length ? '(' + selectedFailureIds.length + ')' : '' }}
                </v-btn>
              </div>
            </div>

            <div v-if="failures.length" class="table-frame failure-table-frame">
              <v-table density="comfortable" class="status-table">
                <thead>
                  <tr>
                    <th class="select-cell">
                      <v-checkbox-btn
                        :model-value="allFailuresSelected"
                        :indeterminate="selectedFailureIds.length > 0 && !allFailuresSelected"
                        aria-label="全选失败任务"
                        :disabled="pending !== null"
                        @update:model-value="toggleAllFailures"
                      />
                    </th>
                    <th>路径</th>
                    <th>失败原因</th>
                    <th>次数</th>
                    <th>更新时间</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in failures" :key="item.id">
                    <td class="select-cell">
                      <v-checkbox-btn
                        :model-value="isFailureSelected(item.id)"
                        :aria-label="'选择失败任务 ' + item.id"
                        :disabled="pending !== null"
                        @update:model-value="value => toggleFailureSelection(item.id, value)"
                      />
                    </td>
                    <td class="path-cell" :title="item.path">{{ item.path }}</td>
                    <td class="failure-reason-cell" :title="item.error || item.repair_hint">
                      <span class="status-chip" :class="failureReasonTone(item)">{{ item.reason_label || '未分类错误' }}</span>
                      <span class="failure-raw-error">{{ item.error || '未返回原始错误' }}</span>
                      <span class="failure-repair-hint">{{ item.repair_hint || item.error || '请查看日志后修复。' }}</span>
                    </td>
                    <td>{{ item.attempts }}</td>
                    <td class="time-cell">{{ formatTime(item.updated_at) }}</td>
                    <td class="action-cell">
                      <v-btn
                        icon="mdi-replay"
                        size="small"
                        variant="text"
                        color="primary"
                        title="重试此任务"
                        aria-label="重试此任务"
                        :loading="pending === item.id"
                        :disabled="pending !== null"
                        @click="retry(item.id)"
                      />
                    </td>
                  </tr>
                </tbody>
              </v-table>
            </div>
            <div v-else class="empty-state">
              <div class="empty-icon empty-icon--success" aria-hidden="true"><v-icon size="19">mdi-check</v-icon></div>
              <strong>系统运行良好</strong>
              <span>暂无未解决的同步失败任务。</span>
            </div>
          </section>

          <section class="content-section" aria-labelledby="cleanup-title">
            <div class="section-heading section-heading--compact">
              <div>
                <h2 id="cleanup-title">待确认清理</h2>
                <p>扫描发现的缺失 STRM 文件。</p>
              </div>
              <span class="section-count" :class="{ 'has-items': status.cleanup_batches.length }">{{ status.cleanup_batches.length }}</span>
            </div>

            <div v-if="status.cleanup_batches.length" class="table-frame">
              <v-table density="comfortable" class="status-table">
                <thead>
                  <tr><th>监控目录</th><th>文件数</th><th>创建时间</th><th></th></tr>
                </thead>
                <tbody>
                  <tr v-for="batch in status.cleanup_batches" :key="batch.batch_id">
                    <td class="path-cell" :title="batch.monitor_root">{{ batch.monitor_root }}</td>
                    <td>{{ batch.path_count }}</td>
                    <td class="time-cell">{{ formatTime(batch.created_at) }}</td>
                    <td class="action-cell">
                      <v-btn
                        icon="mdi-check-circle-outline"
                        size="small"
                        variant="text"
                        color="warning"
                        title="确认清理"
                        aria-label="确认清理"
                        :loading="pending === batch.batch_id"
                        @click="confirmCleanup(batch.batch_id)"
                      />
                    </td>
                  </tr>
                </tbody>
              </v-table>
            </div>
            <div v-else class="empty-state">
              <div class="empty-icon" aria-hidden="true"><v-icon size="19">mdi-shield-check-outline</v-icon></div>
              <strong>没有待确认批次</strong>
              <span>缺失文件会在扫描后显示在这里。</span>
            </div>
          </section>
        </div>
      </section>

          <section v-show="activeTab === 'config'" class="config-view-host" aria-labelledby="config-title">
            <Config
              embedded
              :initial-config="initialConfig"
              :api="props.api"
              @save="handleConfigSave"
              @close="activeTab = 'dashboard'"
            />
          </section>
        </main>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import Config from './Config.vue'
import { unwrapApiResponse } from './api_response.js'
import { readPluginConfig } from './config_persistence.js'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  initialConfig: { type: Object, default: () => ({}) },
  config: { type: Object, default: () => ({}) },
  version: { type: String, default: '2.1.13' },
  defaultTab: { type: String, default: 'dashboard' },
})

const emit = defineEmits(['save'])

const activeTab = ref(props.defaultTab === 'config' ? 'config' : 'dashboard')
const loading = ref(false)
const pending = ref(null)
const error = ref('')
const lastUpdated = ref(null)
const failures = ref([])
const selectedFailureIds = ref([])
const savedConfig = ref(null)
const status = reactive({
  enabled: false,
  reliable_engine: false,
  scan_running: false,
  command_running: false,
  monitor_active: false,
  queue_active: false,
  service_running: false,
  service_busy: false,
  service_state: 'disabled',
  queued: 0,
  active_queued: 0,
  pending_jobs: 0,
  orphaned_queued: 0,
  engine: { memory_queued: 0, inflight: 0, scheduled: 0, workers: 0 },
  scan_progress: {
    running: false,
    run_id: '',
    kind: '',
    phase: 'idle',
    current_rule: '',
    current_path: '',
    total: 0,
    processed: 0,
    failed: 0,
    result_counts: { existing_skipped: 0, copied_non_media: 0, copied_subtitle: 0, generated_strm: 0, failed: 0 },
    started_at: null,
    last_progress_at: null,
    finished_at: null,
    stalled: false,
    stalled_seconds: 0,
  },
  processing_overview: {
    media_total: 0,
    strm_total: 0,
    media_strm_consistent: true,
    non_media_total: 0,
    non_media_completed: 0,
    subtitle_total: 0,
    subtitle_completed: 0,
    ready: false,
    record_ready: false,
    refreshing: false,
    source_scan_pending: false,
    source_scan_error: '',
    last_checked_at: null,
  },
  command_progress: {
    running: false,
    run_id: '',
    label: '',
    monitor_root: '',
    phase: 'idle',
    total: 0,
    processed: 0,
    unchanged: 0,
    skipped: 0,
    failed: 0,
    current_path: '',
    last_progress_at: null,
    started_at: null,
    finished_at: null,
    stalled: false,
    stalled_seconds: 0,
    result_counts: { existing_skipped: 0, copied_non_media: 0, copied_subtitle: 0, generated_strm: 0, failed: 0 },
    errors: [],
  },
  recent_runs: [],
  cleanup_batches: [],
})

const fullScanPending = ref(false)
const version = computed(() => props.version || '2.1.13')
const initialConfig = computed(() => {
  if (savedConfig.value && Object.keys(savedConfig.value).length) return savedConfig.value
  if (props.initialConfig && Object.keys(props.initialConfig).length) return props.initialConfig
  return props.config || {}
})
const runtimeActive = computed(() => Boolean(status.service_busy))
const runtimeLabel = computed(() => {
  if (status.service_state === 'pending_recovery') return '有待恢复任务'
  if (runtimeActive.value) return '同步任务处理中'
  return status.service_running ? '同步服务待机' : (status.enabled ? '同步服务未运行' : '同步服务已停用')
})
const runtimeTitle = computed(() => {
  if (status.command_running) return '手动 /strm 正在执行'
  if (status.scan_running) return '全量扫描正在进行'
  if (status.engine.inflight > 0) return '同步引擎正在处理任务'
  if (status.service_state === 'pending_recovery') return '发现待恢复的持久化任务'
  if (status.service_state === 'monitoring_idle') return '目录监控已启用，当前空闲'
  if (status.service_state === 'engine_idle') return '可靠同步引擎已启用，当前空闲'
  if (status.service_state === 'queue_running') return '可靠同步引擎正在处理队列'
  if (status.service_state === 'enabled_idle') return '同步服务已启用，当前空闲'
  if (!status.enabled) return '同步服务未启用'
  return status.reliable_engine ? '可靠同步引擎已就绪' : '基础同步逻辑已就绪'
})
const runtimeDescription = computed(() => {
  if (status.command_running) return '手动命令完成后会显示成功、未变化、跳过和失败数量。'
  if (status.scan_running) return '新发现的媒体文件会按目录规则生成 STRM。'
  if (status.engine.inflight > 0) return '队列中的任务正在按工作线程逐项处理。'
  if (status.service_state === 'pending_recovery') return `持久化队列中有 ${status.orphaned_queued} 个任务等待可靠同步引擎恢复。`
  if (status.service_state === 'monitoring_idle') return '目录变化会按配置规则触发 STRM 生成。'
  if (status.service_state === 'engine_idle') return '任务队列当前没有正在处理的文件。'
  if (status.service_state === 'queue_running') return '队列中的任务正在等待或按工作线程处理。'
  if (status.service_state === 'enabled_idle') return '监控与任务队列当前没有正在处理的文件。'
  if (!status.enabled) return '启用插件后才会启动监控、扫描或可靠同步服务。'
  return status.reliable_engine ? '队列、失败记录与清理确认均已纳入状态追踪。' : '开启可靠同步后可获得完整的任务追踪能力。'
})
const lastUpdatedLabel = computed(() => lastUpdated.value ? formatTime(lastUpdated.value) : '尚未刷新')
const scanProgress = computed(() => status.scan_progress)
const fullScanProgress = computed(() => scanProgress.value)
const processingOverview = computed(() => status.processing_overview)
const fullScanProgressPercent = computed(() => {
  const total = Number(fullScanProgress.value.total || 0)
  const processed = Number(fullScanProgress.value.processed || 0)
  return total > 0 ? Math.min(100, (processed / total) * 100) : 0
})
const fullScanProgressHasData = computed(() => Boolean(
  fullScanProgress.value.running
  || fullScanProgress.value.run_id
  || fullScanProgress.value.started_at
  || fullScanProgress.value.finished_at
))
const fullScanProgressPhaseLabel = computed(() => ({
  idle: '未开始',
  scanning: '扫描处理中',
  completed: '已完成',
  completed_with_errors: '部分完成',
  failed: '失败',
}[fullScanProgress.value.phase] || fullScanProgress.value.phase || '未知'))
const overviewConsistencyLabel = computed(() => {
  if (!processingOverview.value.record_ready) return '等待核对'
  return processingOverview.value.media_strm_consistent ? '数量一致' : '数量不一致'
})
const overviewConsistencyTone = computed(() => {
  if (!processingOverview.value.record_ready) return 'is-pending'
  return processingOverview.value.media_strm_consistent ? 'is-consistent' : 'is-inconsistent'
})
const commandProgress = computed(() => status.command_progress)
const commandProgressCompleted = computed(() => (
  Number(commandProgress.value.processed || 0)
  + Number(commandProgress.value.unchanged || 0)
  + Number(commandProgress.value.skipped || 0)
  + Number(commandProgress.value.failed || 0)
))
const commandProgressPercent = computed(() => {
  const total = Number(commandProgress.value.total || 0)
  return total > 0 ? Math.min(100, (commandProgressCompleted.value / total) * 100) : 0
})
const commandProgressHasData = computed(() => Boolean(
  commandProgress.value.running
  || commandProgress.value.run_id
  || commandProgress.value.total
  || commandProgress.value.current_path
))
const commandProgressPhaseLabel = computed(() => ({
  idle: '未开始',
  discovering: '发现文件',
  processing: '处理中',
  completed: '已完成',
}[commandProgress.value.phase] || commandProgress.value.phase || '未知'))
const allFailuresSelected = computed(() => (
  failures.value.length > 0
  && failures.value.every(item => selectedFailureIds.value.includes(Number(item.id)))
))
const resultCategories = [
  { key: 'existing_skipped', label: '已有内容跳过', tone: 'muted' },
  { key: 'copied_non_media', label: '复制非媒体', tone: 'neutral' },
  { key: 'copied_subtitle', label: '复制字幕', tone: 'info' },
  { key: 'generated_strm', label: '生成 STRM', tone: 'success' },
  { key: 'failed', label: '失败', tone: 'danger' },
]

function formatTime(value) {
  if (value === null || value === undefined || value === '') return '-'
  const numeric = Number(value)
  const date = Number.isFinite(numeric) && numeric > 0
    ? new Date(numeric < 100000000000 ? numeric * 1000 : numeric)
    : new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function completionPercent(total, completed) {
  const denominator = Number(total || 0)
  const numerator = Number(completed || 0)
  return denominator > 0 ? Math.min(100, Math.max(0, (numerator / denominator) * 100)) : 0
}

function formatDuration(value) {
  const seconds = Math.max(0, Number(value) || 0)
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return remainder ? `${minutes} 分 ${remainder} 秒` : `${minutes} 分钟`
}

function statusTone(value) {
  const normalized = String(value || '').toLowerCase()
  if (['done', 'success', 'completed', 'completed_empty', '完成', '成功'].includes(normalized)) return 'status-chip--success'
  if (['completed_with_errors', 'partial', '部分完成'].includes(normalized)) return 'status-chip--danger'
  if (['failed', 'error', '失败'].includes(normalized)) return 'status-chip--danger'
  if (['pending', 'queued', '排队'].includes(normalized)) return 'status-chip--muted'
  return 'status-chip--active'
}

function displayStatus(value) {
  const labels = { running: '处理中', processing: '处理中', pending: '排队中', queued: '排队中', success: '已完成', completed: '已完成', completed_empty: '无文件', completed_with_errors: '部分完成', done: '已完成', failed: '失败', error: '失败' }
  return labels[String(value || '').toLowerCase()] || value || '未知'
}

function resultItems(run = {}) {
  const rawCounts = run.result_counts || {}
  const counts = {
    ...rawCounts,
    // Keep older task rows readable after the table was reduced to four columns.
    existing_skipped: Number(rawCounts.existing_skipped || 0) || Number(run.skipped || 0),
  }
  return resultCategories
    .map(category => ({ ...category, count: Number(counts[category.key] || 0) }))
    .filter(item => item.count > 0)
}

function applyStatus(data = {}) {
  Object.assign(status, data)
  status.engine = { memory_queued: 0, inflight: 0, scheduled: 0, workers: 0, ...(data.engine || {}) }
  status.scan_progress = {
    ...status.scan_progress,
    ...(data.scan_progress || {}),
    result_counts: {
      ...status.scan_progress.result_counts,
      ...(data.scan_progress?.result_counts || {}),
    },
  }
  status.processing_overview = {
    ...status.processing_overview,
    ...(data.processing_overview || {}),
  }
  status.command_progress = {
    ...status.command_progress,
    ...(data.command_progress || {}),
    result_counts: {
      ...status.command_progress.result_counts,
      ...(data.command_progress?.result_counts || {}),
    },
    errors: Array.isArray(data.command_progress?.errors) ? data.command_progress.errors : [],
  }
  status.recent_runs = Array.isArray(data.recent_runs) ? data.recent_runs : []
  status.cleanup_batches = Array.isArray(data.cleanup_batches) ? data.cleanup_batches : []
}

function pruneFailureSelection() {
  const visibleIds = new Set(failures.value.map(item => Number(item.id)))
  selectedFailureIds.value = selectedFailureIds.value.filter(id => visibleIds.has(Number(id)))
}

function isFailureSelected(failureId) {
  return selectedFailureIds.value.includes(Number(failureId))
}

function toggleFailureSelection(failureId, selected) {
  const normalizedId = Number(failureId)
  if (selected && !isFailureSelected(normalizedId)) {
    selectedFailureIds.value = [...selectedFailureIds.value, normalizedId]
    return
  }
  if (!selected) {
    selectedFailureIds.value = selectedFailureIds.value.filter(id => id !== normalizedId)
  }
}

function toggleAllFailures(value) {
  const shouldSelect = typeof value === 'boolean' ? value : !allFailuresSelected.value
  selectedFailureIds.value = shouldSelect ? failures.value.map(item => Number(item.id)) : []
}

function failureReasonTone(item = {}) {
  return item.retryable ? 'status-chip--warning' : 'status-chip--danger'
}

async function startFullScan() {
  if (!props.api?.post || fullScanPending.value || status.scan_running || status.command_running) return
  fullScanPending.value = true
  error.value = ''
  try {
    const response = await props.api.post('plugin/CloudStrmButler/sync_full_scan', {})
    const result = unwrapApiResponse(response)
    if (result?.code !== 0) throw new Error(result?.msg || '全量处理启动失败')
    await load()
  } catch (err) {
    error.value = err.message || '全量处理启动失败'
  } finally {
    fullScanPending.value = false
  }
}

async function load() {
  if (!props.api?.get || loading.value) return
  loading.value = true
  error.value = ''
  try {
    const [statusResponse, failureResponse] = await Promise.all([
      props.api.get('plugin/CloudStrmButler/sync_status'),
      props.api.get('plugin/CloudStrmButler/sync_failures'),
    ])
    const statusResult = unwrapApiResponse(statusResponse)
    const failureResult = unwrapApiResponse(failureResponse)
    if (statusResult?.code !== 0) throw new Error(statusResult?.msg || '读取状态失败')
    if (failureResult?.code !== 0) throw new Error(failureResult?.msg || '读取失败任务失败')
    applyStatus(statusResult.data || {})
    failures.value = Array.isArray(failureResult?.data?.items) ? failureResult.data.items : []
    pruneFailureSelection()
    lastUpdated.value = Date.now()
  } catch (err) {
    error.value = err.message || '读取状态失败'
  } finally {
    loading.value = false
  }
}

async function loadConfig() {
  if (!props.api?.get) return
  try {
    const persisted = await readPluginConfig(props.api)
    savedConfig.value = { ...persisted }
  } catch (err) {
    error.value = err.message || '读取插件配置失败'
  }
}

async function retry(failureId) {
  pending.value = failureId
  error.value = ''
  try {
    const response = await props.api.post('plugin/CloudStrmButler/sync_retry_failure', { failure_id: failureId })
    const result = unwrapApiResponse(response)
    if (result?.code !== 0) throw new Error(result?.msg || '重试失败')
    await load()
  } catch (err) {
    error.value = err.message || '重试失败'
  } finally {
    pending.value = null
  }
}

async function retrySelected() {
  const failureIds = [...selectedFailureIds.value]
  if (!failureIds.length || !props.api?.post) return
  pending.value = 'failure-batch'
  error.value = ''
  try {
    const response = await props.api.post('plugin/CloudStrmButler/sync_retry_failures', { failure_ids: failureIds })
    const result = unwrapApiResponse(response)
    if (result?.code !== 0) throw new Error(result?.msg || '批量重试失败')
    selectedFailureIds.value = []
    await load()
  } catch (err) {
    error.value = err.message || '批量重试失败'
  } finally {
    pending.value = null
  }
}

async function confirmCleanup(batchId) {
  pending.value = batchId
  error.value = ''
  try {
    const response = await props.api.post('plugin/CloudStrmButler/sync_confirm_cleanup', { batch_id: batchId })
    const result = unwrapApiResponse(response)
    if (result?.code !== 0) throw new Error(result?.msg || '清理失败')
    await load()
  } catch (err) {
    error.value = err.message || '清理失败'
  } finally {
    pending.value = null
  }
}

async function handleConfigSave(payload) {
  savedConfig.value = payload && typeof payload === 'object' ? { ...payload } : null
  emit('save', payload)
  await load()
}

let refreshTimer = null
let pageDisposed = false

onMounted(async () => {
  pageDisposed = false
  await loadConfig()
  await load()
  if (!pageDisposed) refreshTimer = window.setInterval(load, 5000)
})

onUnmounted(() => {
  pageDisposed = true
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style scoped>
.cloudstrm-shell {
  --cs-bg: #121218;
  --cs-surface: #181820;
  --cs-surface-raised: #1c1c24;
  --cs-surface-inset: #101016;
  --cs-line: #2a2a35;
  --cs-line-strong: #3d3d4c;
  --cs-text: #f5f3fb;
  --cs-muted: #a5a2b1;
  --cs-dim: #72707e;
  --cs-primary: #7c4dff;
  --cs-primary-soft: #b59cff;
  --cs-success: #59d39b;
  --cs-warning: #e7b764;
  --cs-danger: #ff7f92;
  background: #0f1015;
  color: var(--cs-text);
  min-height: 100vh;
  font-family: "SF Pro Display", "PingFang SC", "Microsoft YaHei", sans-serif;
  letter-spacing: 0;
  line-height: 1.45;
}

.shell-frame {
  background: var(--cs-bg);
  border: 1px solid #252630;
  border-radius: 10px;
  box-shadow: 0 18px 48px rgba(0, 0, 0, .22);
  margin: 24px auto;
  max-width: 1400px;
  min-height: calc(100vh - 48px);
  overflow: hidden;
}

.shell-header {
  background: var(--cs-surface);
  min-height: 126px;
  padding: 0 24px;
  position: relative;
}

.shell-header-top {
  align-items: center;
  display: flex;
  justify-content: space-between;
  min-height: 72px;
}

.brand-lockup,
.header-actions,
.runtime-indicator,
.section-heading,
.metric-heading,
.page-intro,
.runtime-banner,
.banner-copy,
.empty-state {
  align-items: center;
  display: flex;
}

.brand-lockup { gap: 12px; min-width: 0; }
.brand-mark {
  align-items: center;
  background: rgba(124, 77, 255, .16);
  border: 1px solid rgba(181, 156, 255, .34);
  border-radius: 8px;
  color: var(--cs-primary-soft);
  display: flex;
  flex: 0 0 38px;
  height: 38px;
  justify-content: center;
  width: 38px;
}
.brand-copy { min-width: 0; }
.brand-title { font-size: 16px; font-weight: 700; line-height: 1.2; white-space: nowrap; }
.brand-version { color: var(--cs-dim); font-size: 12px; font-weight: 500; margin-left: 7px; }
.brand-subtitle { color: var(--cs-dim); font-size: 11px; margin-top: 4px; }

.header-actions { gap: 14px; justify-content: flex-end; }
.runtime-indicator { color: var(--cs-muted); font-size: 12px; gap: 7px; white-space: nowrap; }
.runtime-dot { background: var(--cs-dim); border-radius: 50%; height: 7px; width: 7px; }
.runtime-indicator.is-active { color: var(--cs-success); }
.runtime-indicator.is-active .runtime-dot { background: var(--cs-success); box-shadow: 0 0 0 4px rgba(89, 211, 155, .12); }

.tab-bar { align-self: stretch; display: flex; gap: 3px; margin-left: 0; }
.tab-button {
  align-items: center;
  background: transparent;
  border: 0;
  border-bottom: 3px solid transparent;
  color: var(--cs-muted);
  cursor: pointer;
  display: inline-flex;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  gap: 8px;
  min-height: 54px;
  padding: 0 17px;
  transition: background-color .18s ease, border-color .18s ease, color .18s ease;
}
.tab-button:hover { background: rgba(255, 255, 255, .025); color: var(--cs-text); }
.tab-button:focus-visible { outline: 2px solid var(--cs-primary-soft); outline-offset: -3px; }
.tab-button.is-active { background: rgba(255, 255, 255, .025); border-bottom-color: var(--cs-primary); color: var(--cs-primary-soft); }

.shell-divider { background: var(--cs-line); height: 1px; }
.shell-content { margin: 0 auto; max-width: 1340px; padding: 34px 48px 52px; }
.shell-alert { margin-bottom: 22px; }

.page-intro { align-items: flex-end; display: grid; gap: 24px; grid-template-columns: minmax(0, 1fr) auto auto; justify-content: space-between; margin-bottom: 24px; }
.intro-actions { align-items: flex-end; display: flex; flex-direction: column; gap: 7px; margin-left: 24px; }
.intro-actions > span { color: var(--cs-dim); font-size: 11px; text-align: right; }
.eyebrow { color: var(--cs-primary-soft); display: block; font-size: 10px; font-weight: 800; letter-spacing: 1.1px; margin-bottom: 8px; }
h1, h2, p { margin: 0; }
h1 { font-size: 25px; font-weight: 700; line-height: 1.2; }
.page-intro p { color: var(--cs-muted); font-size: 13px; margin-top: 8px; }
.intro-meta { border-left: 1px solid var(--cs-line); min-width: 126px; padding-left: 16px; }
.meta-label { color: var(--cs-dim); display: block; font-size: 11px; margin-bottom: 4px; }
.intro-meta strong { color: var(--cs-muted); font-size: 12px; font-weight: 500; }

.runtime-banner {
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: 8px;
  gap: 12px;
  margin-bottom: 18px;
  min-height: 64px;
  padding: 12px 15px;
}
.runtime-banner.is-active { border-color: rgba(89, 211, 155, .28); }
.banner-icon {
  align-items: center;
  background: rgba(124, 77, 255, .14);
  border-radius: 7px;
  color: var(--cs-primary-soft);
  display: flex;
  flex: 0 0 34px;
  height: 34px;
  justify-content: center;
  width: 34px;
}
.runtime-banner.is-active .banner-icon { background: rgba(89, 211, 155, .12); color: var(--cs-success); }
.banner-copy { align-items: flex-start; flex: 1; flex-direction: column; gap: 2px; min-width: 0; }
.banner-copy strong { font-size: 13px; font-weight: 650; }
.banner-copy span { color: var(--cs-muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.metric-grid { display: grid; gap: 12px; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 30px; }
.engine-metrics-section { border-top: 1px solid var(--cs-line); padding-top: 24px; }
.scope-note { color: var(--cs-dim); font-size: 11px; white-space: nowrap; }
.metric-tile {
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: 8px;
  min-height: 116px;
  padding: 15px 16px 13px;
}
.metric-tile--accent { border-color: rgba(124, 77, 255, .48); }
.metric-heading { color: var(--cs-muted); font-size: 12px; justify-content: space-between; }
.metric-heading .v-icon { color: var(--cs-dim); }
.metric-tile--accent .metric-heading .v-icon { color: var(--cs-primary-soft); }
.metric-tile strong { display: block; font-size: 28px; font-weight: 700; line-height: 1; margin-top: 20px; }
.metric-tile--accent strong { color: var(--cs-primary-soft); }
.metric-caption { color: var(--cs-dim); display: block; font-size: 11px; margin-top: 8px; }

.processing-overview-section { border-top: 1px solid var(--cs-line); margin-bottom: 24px; padding-top: 24px; }
.overview-refresh-state { color: var(--cs-dim); font-size: 11px; white-space: nowrap; }
.overview-refresh-state.is-ready { color: var(--cs-success); }
.processing-overview-grid { display: grid; gap: 12px; grid-template-columns: minmax(0, 1.2fr) minmax(360px, .8fr); }
.processing-overview-card {
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: 8px;
  min-height: 154px;
  padding: 16px 18px 15px;
}
.processing-overview-card--strm { border-color: rgba(124, 77, 255, .42); }
.overview-card-heading { align-items: center; color: var(--cs-muted); display: flex; font-size: 12px; justify-content: space-between; }
.overview-card-heading .v-icon { color: var(--cs-dim); }
.processing-overview-card--strm .overview-card-heading .v-icon { color: var(--cs-primary-soft); }
.overview-pair { align-items: baseline; display: flex; gap: 6px; margin-top: 22px; min-width: 0; }
.overview-pair strong { color: var(--cs-text); font-size: 26px; font-weight: 700; line-height: 1; }
.processing-overview-card--strm .overview-pair strong:last-of-type { color: var(--cs-primary-soft); }
.overview-pair span { color: var(--cs-muted); font-size: 11px; white-space: nowrap; }
.overview-pair .overview-divider { color: var(--cs-dim); font-size: 17px; margin: 0 2px; }
.overview-card-note { color: var(--cs-dim); display: block; font-size: 11px; margin-top: 9px; }
.overview-card-status { align-items: center; display: inline-flex; font-size: 11px; gap: 4px; margin-top: 10px; }
.overview-card-status.is-consistent { color: var(--cs-success); }
.overview-card-status.is-inconsistent { color: var(--cs-danger); }
.overview-card-status.is-pending { color: var(--cs-warning); }
.processing-overview-card--side { display: flex; flex-direction: column; gap: 12px; }
.overview-side-caption { color: var(--cs-dim); font-size: 11px; }
.overview-stat-row { display: grid; gap: 8px 12px; grid-template-columns: minmax(105px, 1fr) auto auto; min-width: 0; }
.overview-stat-row .v-progress-linear { grid-column: 1 / -1; }
.overview-stat-label { align-items: center; color: var(--cs-muted); display: flex; font-size: 12px; gap: 7px; min-width: 0; }
.overview-stat-label .v-icon { color: var(--cs-dim); }
.overview-stat-row strong { color: var(--cs-text); font-size: 14px; font-weight: 650; white-space: nowrap; }
.overview-stat-completed { color: var(--cs-success) !important; font-size: 12px !important; font-weight: 500 !important; }
.overview-stat-completed--subtitle { color: var(--cs-warning) !important; }
.overview-stat-row--subtitle { margin-top: 2px; }

.command-progress-frame {
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: 8px;
  padding: 18px;
}
.full-scan-frame { padding: 17px 22px 19px; }
.full-scan-toolbar { align-items: center; display: flex; gap: 14px; min-height: 30px; }
.scan-state { align-items: center; border: 1px solid var(--cs-line); border-radius: 5px; display: inline-flex; font-size: 11px; gap: 6px; padding: 5px 8px; white-space: nowrap; }
.scan-state--running { background: rgba(89, 211, 155, .12); border-color: rgba(89, 211, 155, .25); color: var(--cs-success); }
.scan-state--done { background: rgba(89, 211, 155, .1); border-color: rgba(89, 211, 155, .2); color: var(--cs-success); }
.scan-state--idle { background: rgba(165, 162, 177, .08); color: var(--cs-muted); }
.scan-state-dot { background: currentColor; border-radius: 50%; height: 6px; width: 6px; }
.full-scan-label { color: var(--cs-muted); font-size: 12px; }
.full-scan-label span { color: var(--cs-dim); margin: 0 5px; }
.full-scan-state { color: var(--cs-dim); font-size: 11px; margin-left: auto; }
.full-scan-details { display: grid; gap: 12px; grid-template-columns: minmax(180px, .7fr) minmax(0, 1.7fr); margin: 15px 0 13px; }
.full-scan-detail { min-width: 0; }
.full-scan-detail span { color: var(--cs-dim); display: block; font-size: 11px; }
.full-scan-detail strong { color: var(--cs-muted); display: block; font-size: 12px; margin-top: 5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.full-scan-detail--path strong { color: var(--cs-text); }
.full-scan-footer { color: var(--cs-dim); display: flex; font-size: 11px; justify-content: space-between; margin-top: 10px; }
.command-progress-top { align-items: flex-start; display: flex; justify-content: space-between; margin-bottom: 13px; }
.command-progress-copy strong { display: block; font-size: 24px; line-height: 1.1; margin-top: 3px; }
.command-progress-copy > span:last-child { color: var(--cs-dim); display: block; font-size: 11px; margin-top: 6px; }
.command-detail-grid { display: grid; gap: 12px; grid-template-columns: minmax(130px, .65fr) minmax(0, 2fr) minmax(150px, .8fr); margin-top: 18px; }
.command-detail { background: var(--cs-surface-inset); border: 1px solid var(--cs-line); border-radius: 6px; min-width: 0; padding: 10px 11px; }
.command-detail span { color: var(--cs-dim); display: block; font-size: 11px; }
.command-detail strong { color: var(--cs-muted); display: block; font-size: 12px; margin-top: 5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.command-detail--path strong { color: var(--cs-text); }
.stalled-warning { align-items: flex-start; background: rgba(231, 183, 100, .1); border: 1px solid rgba(231, 183, 100, .28); border-radius: 6px; color: var(--cs-warning); display: flex; font-size: 12px; gap: 8px; line-height: 1.45; margin-top: 14px; padding: 10px 11px; }
.result-summary-heading { align-items: center; display: flex; justify-content: space-between; margin-top: 20px; }
.result-summary-heading strong { font-size: 13px; }
.result-summary-heading span { font-size: 11px; }
.result-category-grid { display: grid; gap: 9px; grid-template-columns: repeat(5, minmax(0, 1fr)); margin-top: 10px; }
.result-category { background: var(--cs-surface-inset); border: 1px solid var(--cs-line); border-radius: 6px; min-width: 0; padding: 10px 11px; }
.result-category span { color: var(--cs-muted); display: block; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.result-category strong { display: block; font-size: 20px; line-height: 1; margin-top: 8px; }
.result-category--muted strong { color: var(--cs-muted); }
.result-category--neutral strong { color: var(--cs-text); }
.result-category--info strong { color: #79c8ff; }
.result-category--success strong { color: var(--cs-success); }
.result-category--danger strong { color: var(--cs-danger); }
.command-errors { color: var(--cs-danger); font-size: 11px; line-height: 1.5; margin: 13px 0 0; padding-left: 19px; }

.content-section { margin-bottom: 32px; min-width: 0; }
.section-heading { align-items: flex-start; justify-content: space-between; margin-bottom: 12px; }
.section-heading--compact { align-items: center; }
.failure-actions { align-items: center; display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
h2 { font-size: 15px; font-weight: 700; line-height: 1.3; }
.section-heading p { color: var(--cs-dim); font-size: 12px; margin-top: 5px; }
.section-count {
  align-items: center;
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: 5px;
  color: var(--cs-dim);
  display: inline-flex;
  font-size: 11px;
  height: 25px;
  justify-content: center;
  min-width: 25px;
  padding: 0 7px;
}
.section-count.has-items { border-color: rgba(255, 127, 146, .35); color: var(--cs-danger); }

.table-frame {
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: 8px;
  overflow-x: auto;
}
.status-table { background: transparent; color: var(--cs-text); min-width: 600px; }
.failure-table-frame .status-table { min-width: 860px; }
.status-table :deep(table) { width: 100%; }
.status-table :deep(th) {
  background: rgba(255, 255, 255, .018);
  border-bottom: 1px solid var(--cs-line) !important;
  color: var(--cs-dim) !important;
  font-size: 11px;
  font-weight: 600;
  height: 39px;
  white-space: nowrap;
}
.status-table :deep(td) { border-bottom: 1px solid rgba(42, 42, 53, .72) !important; color: var(--cs-muted); font-size: 12px; height: 49px; }
.status-table :deep(tr:last-child td) { border-bottom: 0 !important; }
.status-table :deep(tbody tr:hover) { background: rgba(255, 255, 255, .025); }
.time-cell { color: var(--cs-muted) !important; font-variant-numeric: tabular-nums; white-space: nowrap; }
.path-cell { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.select-cell { text-align: center; width: 46px; }
.select-cell :deep(.v-selection-control) { justify-content: center; }
.failure-reason-cell { max-width: 360px; min-width: 230px; }
.failure-raw-error { color: var(--cs-muted); display: block; font-size: 11px; line-height: 1.35; margin-top: 5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.failure-repair-hint { color: var(--cs-dim); display: block; font-size: 11px; line-height: 1.35; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.result-cell { max-width: 360px; min-width: 230px; }
.result-inline { border-radius: 3px; display: inline-block; font-size: 10px; line-height: 1.2; margin: 2px 5px 2px 0; padding: 4px 5px; white-space: nowrap; }
.result-inline--muted { background: rgba(165, 162, 177, .1); color: var(--cs-muted); }
.result-inline--neutral { background: rgba(245, 243, 251, .08); color: var(--cs-text); }
.result-inline--info { background: rgba(121, 200, 255, .1); color: #79c8ff; }
.result-inline--success { background: rgba(89, 211, 155, .12); color: var(--cs-success); }
.result-inline--danger { background: rgba(255, 127, 146, .12); color: var(--cs-danger); }
.muted-value { color: var(--cs-dim); }
.action-cell { text-align: right; width: 54px; }
.danger-number { color: var(--cs-danger) !important; }
.empty-row { color: var(--cs-dim) !important; height: 90px !important; text-align: center; }
.status-chip {
  border: 1px solid transparent;
  border-radius: 4px;
  display: inline-flex;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  padding: 5px 7px;
}
.status-chip--active { background: rgba(124, 77, 255, .14); border-color: rgba(181, 156, 255, .2); color: var(--cs-primary-soft); }
.status-chip--success { background: rgba(89, 211, 155, .12); border-color: rgba(89, 211, 155, .2); color: var(--cs-success); }
.status-chip--danger { background: rgba(255, 127, 146, .12); border-color: rgba(255, 127, 146, .2); color: var(--cs-danger); }
.status-chip--warning { background: rgba(231, 183, 100, .12); border-color: rgba(231, 183, 100, .25); color: var(--cs-warning); }
.status-chip--muted { background: rgba(165, 162, 177, .1); border-color: rgba(165, 162, 177, .18); color: var(--cs-muted); }

.dashboard-columns { display: grid; gap: 28px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.dashboard-columns .content-section { margin-bottom: 0; }
.empty-state {
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: 8px;
  flex-direction: column;
  justify-content: center;
  min-height: 150px;
  padding: 24px;
  text-align: center;
}
.empty-icon {
  align-items: center;
  background: rgba(165, 162, 177, .1);
  border: 1px solid rgba(165, 162, 177, .18);
  border-radius: 50%;
  color: var(--cs-muted);
  display: flex;
  height: 34px;
  justify-content: center;
  margin-bottom: 11px;
  width: 34px;
}
.empty-icon--success { background: rgba(89, 211, 155, .11); border-color: rgba(89, 211, 155, .24); color: var(--cs-success); }
.empty-state strong { font-size: 13px; font-weight: 650; }
.empty-state span { color: var(--cs-dim); font-size: 12px; margin-top: 5px; }

.config-view-host { min-width: 0; }

@media (max-width: 900px) {
  .shell-frame { border-radius: 0; margin: 0; max-width: none; min-height: 100vh; }
  .shell-header { padding: 0 18px; }
  .tab-button { min-height: 50px; padding: 0 14px; }
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .processing-overview-grid { grid-template-columns: 1fr; }
  .processing-overview-card--side { min-height: 150px; }
  .result-category-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .command-detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .command-detail--path { grid-column: 1 / -1; }
  .dashboard-columns { grid-template-columns: 1fr; }
  .shell-content { padding: 26px 28px 40px; }
}

@media (max-width: 560px) {
  .shell-header { min-height: 116px; }
  .shell-header-top { min-height: 66px; }
  .brand-subtitle, .runtime-indicator { display: none; }
  .brand-title { font-size: 14px; }
  .brand-mark { flex-basis: 34px; height: 34px; width: 34px; }
  .shell-content { padding: 22px 14px 32px; }
  .page-intro { align-items: flex-start; display: flex; flex-direction: column; gap: 16px; }
  .section-heading--compact { align-items: flex-start; flex-direction: column; gap: 10px; }
  .failure-actions { justify-content: flex-start; width: 100%; }
  .intro-actions { align-items: flex-start; margin-left: 0; width: 100%; }
  .intro-actions > span { text-align: left; }
  .intro-meta { border-left: 0; border-top: 1px solid var(--cs-line); padding-left: 0; padding-top: 10px; width: 100%; }
  .runtime-banner { align-items: flex-start; }
  .banner-copy span { white-space: normal; }
  .scope-note { text-align: right; white-space: normal; }
  .metric-grid { gap: 9px; }
  .result-category-grid, .command-detail-grid { grid-template-columns: 1fr 1fr; }
  .result-category:last-child { grid-column: 1 / -1; }
  .overview-stat-row { grid-template-columns: minmax(100px, 1fr) auto; }
  .overview-stat-completed { grid-column: 2; grid-row: 1; }
  .full-scan-toolbar { align-items: flex-start; flex-wrap: wrap; }
  .full-scan-state { margin-left: 0; width: 100%; }
  .full-scan-details { grid-template-columns: 1fr; }
  .full-scan-footer { align-items: flex-start; flex-direction: column; gap: 4px; }
  .metric-tile { min-height: 116px; padding: 13px; }
  .metric-tile strong { font-size: 25px; margin-top: 18px; }
  .dashboard-columns { gap: 24px; }
}

/* Reference workbench treatment: a quiet light canvas with a fixed navigation rail. */
.cloudstrm-shell {
  --cs-bg: #fbfcfe;
  --cs-surface: #ffffff;
  --cs-surface-raised: #f4f8fb;
  --cs-surface-inset: #f7f9fb;
  --cs-line: #dbe3eb;
  --cs-line-strong: #bdc9d5;
  --cs-text: #24314a;
  --cs-muted: #66758c;
  --cs-dim: #8d99aa;
  --cs-primary: #2d6073;
  --cs-primary-soft: #4c8390;
  --cs-success: #48a476;
  --cs-warning: #d79a3f;
  --cs-danger: #b9633e;
  background: #e7edf3;
  color: var(--cs-text);
}

.shell-frame {
  background: var(--cs-bg);
  border: 0;
  border-radius: 14px;
  box-shadow: 0 12px 34px rgba(24, 38, 64, .1);
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr);
  margin: 28px auto;
  max-width: 1496px;
  min-height: calc(100vh - 56px);
  overflow: hidden;
  width: calc(100% - 56px);
}

.shell-sidebar {
  background: #15243a;
  color: #d6dfeb;
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 34px 26px 28px;
}

.shell-sidebar .brand-lockup { align-items: flex-start; gap: 13px; }
.shell-sidebar .brand-mark {
  background: #d87348;
  border: 0;
  border-radius: 8px;
  color: #ffffff;
  flex-basis: 34px;
  height: 34px;
  width: 34px;
}
.shell-sidebar .brand-title { color: #ffffff; font-size: 16px; }
.shell-sidebar .brand-version { color: #9db0c7; }
.shell-sidebar .brand-subtitle { color: #aebbd0; margin-top: 4px; }

.sidebar-nav { display: flex; flex-direction: column; gap: 4px; margin-top: 43px; }
.sidebar-nav-label {
  color: #8d9bb3;
  font-size: 12px;
  font-weight: 700;
  margin-bottom: 8px;
}
.sidebar-nav-label--status { margin-bottom: 12px; margin-top: 42px; }
.sidebar-nav-button {
  align-items: center;
  background: transparent;
  border: 0;
  border-radius: 7px;
  color: #c9d3e1;
  cursor: pointer;
  display: inline-flex;
  font: inherit;
  font-size: 14px;
  font-weight: 500;
  gap: 14px;
  min-height: 44px;
  padding: 0 18px;
  position: relative;
  text-align: left;
  transition: background-color .18s ease, color .18s ease;
}
.sidebar-nav-button:hover { background: rgba(255, 255, 255, .06); color: #ffffff; }
.sidebar-nav-button:focus-visible { outline: 2px solid #e79851; outline-offset: -2px; }
.sidebar-nav-button.is-active { background: #27435b; color: #ffffff; font-weight: 700; }
.sidebar-nav-button.is-active::before {
  background: #e79851;
  border-radius: 0 2px 2px 0;
  content: '';
  height: 44px;
  left: 0;
  position: absolute;
  top: 0;
  width: 4px;
}
.sidebar-nav-button .v-icon { color: #b9c6d7; }
.sidebar-nav-button.is-active .v-icon { color: #ffffff; }

.sidebar-runtime-state { align-items: flex-start; display: flex; gap: 10px; }
.sidebar-runtime-state .runtime-dot { background: #65bd93; flex: 0 0 10px; height: 10px; margin-top: 4px; width: 10px; }
.sidebar-runtime-state .runtime-dot:not(.is-active) { background: #7f8da1; }
.sidebar-runtime-state strong, .sidebar-runtime-state span { display: block; }
.sidebar-runtime-state strong { color: #d6dfeb; font-size: 13px; font-weight: 700; }
.sidebar-runtime-state span { color: #8d9bb3; font-size: 11px; margin-top: 5px; }

.sidebar-health { background: #1d314a; border-radius: 8px; margin-top: auto; padding: 14px 16px; }
.sidebar-health-heading { align-items: center; display: flex; gap: 9px; }
.sidebar-health-icon { align-items: center; background: #417a66; border-radius: 50%; color: #ffffff; display: flex; height: 18px; justify-content: center; width: 18px; }
.sidebar-health strong { color: #e7edf6; font-size: 12px; font-weight: 700; }
.sidebar-health > span { color: #9db0c7; display: block; font-size: 11px; margin-top: 10px; }

.shell-main { background: var(--cs-bg); min-width: 0; }
.shell-header { align-items: center; background: var(--cs-bg); display: flex; justify-content: flex-end; min-height: 76px; padding: 0 48px; }
.mobile-brand { display: none; }
.header-actions { gap: 15px; }
.runtime-indicator { color: var(--cs-muted); font-size: 12px; gap: 7px; }
.runtime-dot { background: var(--cs-dim); border-radius: 50%; height: 7px; width: 7px; }
.runtime-indicator.is-active { color: var(--cs-success); }
.runtime-indicator.is-active .runtime-dot { background: var(--cs-success); box-shadow: 0 0 0 4px rgba(72, 164, 118, .14); }
.shell-divider { background: #e2e8ef; height: 1px; }
.shell-content { max-width: none; padding: 36px 48px 58px; }

.page-intro { gap: 26px; margin-bottom: 28px; }
.eyebrow { color: var(--cs-primary); }
h1 { color: var(--cs-text); font-size: 24px; }
.page-intro p { color: var(--cs-muted); font-size: 14px; }
.intro-meta { border-left-color: var(--cs-line); }
.meta-label, .intro-meta strong { color: var(--cs-muted); }
.intro-actions > span { color: var(--cs-dim); }
.cloudstrm-shell :deep(.v-btn) { border-radius: 6px; letter-spacing: 0; text-transform: none; }
.cloudstrm-shell :deep(.v-btn--variant-flat) { background: var(--cs-primary); color: #ffffff; }
.cloudstrm-shell :deep(.v-btn--variant-outlined) { border-color: var(--cs-line-strong); color: var(--cs-text); }
.cloudstrm-shell :deep(.v-btn--variant-tonal) { background: #e6f0f3; color: var(--cs-primary); }

.runtime-banner {
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-left: 8px solid var(--cs-success);
  border-radius: 8px;
  box-shadow: 0 4px 8px rgba(23, 32, 56, .07);
  gap: 16px;
  margin-bottom: 30px;
  min-height: 108px;
  padding: 22px 24px;
}
.runtime-banner:not(.is-active) { border-left-color: var(--cs-dim); }
.banner-icon { background: #e6f5ed; border-radius: 50%; color: #34825e; flex-basis: 50px; height: 50px; width: 50px; }
.runtime-banner:not(.is-active) .banner-icon { background: #f0f3f6; color: var(--cs-muted); }
.banner-copy strong { color: var(--cs-text); font-size: 16px; }
.banner-copy span { color: var(--cs-muted); font-size: 13px; }
.runtime-banner :deep(.v-chip) { background: #e7f5ec !important; color: #2d7052 !important; }
.runtime-banner:not(.is-active) :deep(.v-chip) { background: #eff3f6 !important; color: var(--cs-muted) !important; }

.engine-metrics-section, .processing-overview-section { border-top: 0; padding-top: 0; }
.content-section { margin-bottom: 30px; }
.section-heading { margin-bottom: 14px; }
h2 { color: var(--cs-text); font-size: 17px; }
.section-heading p { color: var(--cs-muted); font-size: 12px; }
.overview-refresh-state { color: var(--cs-muted); }
.overview-refresh-state.is-ready { color: var(--cs-success); }
.metric-grid { gap: 16px; margin-bottom: 0; }
.metric-tile, .processing-overview-card, .command-progress-frame, .table-frame, .empty-state {
  background: var(--cs-surface);
  border-color: var(--cs-line);
  border-radius: 8px;
  box-shadow: none;
}
.metric-tile { min-height: 110px; padding: 18px 20px 16px; }
.metric-tile--accent { border-color: rgba(72, 164, 118, .45); }
.metric-heading { color: var(--cs-muted); }
.metric-heading .v-icon { color: var(--cs-dim); }
.metric-tile--accent .metric-heading .v-icon { color: var(--cs-success); }
.metric-tile strong { color: var(--cs-text); font-size: 29px; margin-top: 16px; }
.metric-tile--accent strong { color: var(--cs-success); }
.metric-caption { color: var(--cs-dim); }

.processing-overview-section { margin-bottom: 30px; }
.processing-overview-grid { gap: 16px; grid-template-columns: minmax(0, 1.2fr) minmax(340px, .8fr); }
.processing-overview-card { min-height: 154px; padding: 18px 20px 16px; }
.processing-overview-card--strm { border-color: rgba(45, 96, 115, .3); }
.overview-card-heading { color: var(--cs-muted); }
.overview-card-heading .v-icon { color: var(--cs-primary); }
.overview-pair strong { color: var(--cs-text); }
.processing-overview-card--strm .overview-pair strong:last-of-type { color: var(--cs-primary); }
.overview-pair span, .overview-card-note, .overview-side-caption { color: var(--cs-muted); }
.overview-card-status.is-consistent { color: var(--cs-success); }
.overview-card-status.is-inconsistent { color: var(--cs-danger); }
.overview-card-status.is-pending { color: var(--cs-warning); }
.overview-stat-label { color: var(--cs-muted); }
.overview-stat-label .v-icon { color: var(--cs-dim); }
.overview-stat-row strong { color: var(--cs-text); }
.overview-stat-completed { color: var(--cs-success) !important; }
.overview-stat-completed--subtitle { color: var(--cs-warning) !important; }
.cloudstrm-shell :deep(.v-progress-linear) { --v-theme-primary: 45, 96, 115; --v-theme-success: 72, 164, 118; --v-theme-warning: 215, 154, 63; }

.command-progress-frame { padding: 20px; }
.full-scan-frame { padding: 18px 22px 20px; }
.scan-state, .status-chip { border-radius: 999px; }
.scan-state { border-color: var(--cs-line); color: var(--cs-muted); }
.scan-state--running, .scan-state--done { background: #e7f5ec; border-color: #c6e6d2; color: #2d7052; }
.scan-state--idle { background: #eff3f6; color: var(--cs-muted); }
.full-scan-label, .full-scan-detail span, .full-scan-footer, .command-detail span { color: var(--cs-muted); }
.full-scan-detail strong, .command-detail strong { color: var(--cs-text); }
.command-detail { background: var(--cs-surface-raised); border-color: var(--cs-line); }
.result-summary-heading strong { color: var(--cs-text); }
.result-category { background: var(--cs-surface-raised); border-color: var(--cs-line); }
.result-category span { color: var(--cs-muted); }
.result-category--muted strong { color: var(--cs-muted); }
.result-category--neutral strong { color: var(--cs-text); }
.result-category--info strong { color: var(--cs-primary); }
.result-category--success strong { color: var(--cs-success); }
.result-category--danger strong, .danger-number { color: var(--cs-danger) !important; }
.stalled-warning { background: #fff7ed; border-color: #f0d2b3; color: #935237; }

.table-frame { overflow-x: auto; }
.status-table { color: var(--cs-text); }
.status-table :deep(th) { background: #f7f9fb; border-bottom-color: var(--cs-line) !important; color: var(--cs-dim) !important; }
.status-table :deep(td) { border-bottom-color: #e8edf2 !important; color: var(--cs-muted); }
.status-table :deep(tbody tr:hover) { background: #f7f9fb; }
.status-chip--active { background: #e6f0f3; border-color: #c9dce2; color: var(--cs-primary); }
.status-chip--success { background: #e7f5ec; border-color: #c6e6d2; color: #2d7052; }
.status-chip--danger { background: #fff0e5; border-color: #f0cfad; color: var(--cs-danger); }
.status-chip--muted { background: #eff3f6; border-color: var(--cs-line); color: var(--cs-muted); }
.section-count { background: var(--cs-surface); border-color: var(--cs-line); color: var(--cs-muted); }
.section-count.has-items { border-color: #f0cfad; color: var(--cs-danger); }
.empty-icon { background: #eff3f6; border-color: var(--cs-line); color: var(--cs-muted); }
.empty-icon--success { background: #e6f5ed; border-color: #c6e6d2; color: var(--cs-success); }
.empty-state strong { color: var(--cs-text); }
.empty-state span { color: var(--cs-muted); }

@media (max-width: 900px) {
  .shell-frame { grid-template-columns: 212px minmax(0, 1fr); margin: 18px; min-height: calc(100vh - 36px); width: calc(100% - 36px); }
  .shell-sidebar { padding: 26px 18px 22px; }
  .shell-header { padding: 0 28px; }
  .shell-content { padding: 28px; }
  .processing-overview-grid { grid-template-columns: 1fr; }
}

@media (max-width: 700px) {
  .cloudstrm-shell { background: var(--cs-bg); }
  .shell-frame { border-radius: 0; display: block; margin: 0; min-height: 100vh; width: 100%; }
  .shell-sidebar { padding: 18px 16px 16px; }
  .shell-sidebar .brand-subtitle, .shell-sidebar .brand-version { display: none; }
  .sidebar-nav { display: grid; gap: 4px; grid-template-columns: 1fr 1fr; margin-top: 20px; }
  .sidebar-nav-label { grid-column: 1 / -1; margin-bottom: 4px; }
  .sidebar-nav-label--status, .sidebar-runtime-state { display: none; }
  .sidebar-health { margin-top: 14px; }
  .shell-header { min-height: 62px; padding: 0 16px; }
  .mobile-brand { align-items: center; display: flex; margin-right: auto; }
  .mobile-brand .brand-mark { background: #d87348; border: 0; color: #ffffff; flex-basis: 32px; height: 32px; width: 32px; }
  .mobile-brand .brand-title { color: var(--cs-text); font-size: 14px; }
  .runtime-indicator { display: none; }
  .shell-content { padding: 24px 16px 36px; }
  .page-intro { align-items: flex-start; display: flex; flex-direction: column; gap: 16px; }
  .intro-actions { align-items: flex-start; margin-left: 0; width: 100%; }
  .intro-actions > span { text-align: left; }
  .intro-meta { border-left: 0; border-top: 1px solid var(--cs-line); padding-left: 0; padding-top: 10px; width: 100%; }
  .runtime-banner { align-items: flex-start; margin-bottom: 24px; padding: 18px; }
  .banner-copy span { white-space: normal; }
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .processing-overview-grid { grid-template-columns: 1fr; }
  .full-scan-toolbar { align-items: flex-start; flex-wrap: wrap; }
  .full-scan-state { margin-left: 0; width: 100%; }
  .full-scan-details { grid-template-columns: 1fr; }
  .full-scan-footer { align-items: flex-start; flex-direction: column; gap: 4px; }
}

@media (max-width: 420px) {
  .metric-grid { gap: 9px; }
  .metric-tile { padding: 14px; }
  .metric-tile strong { font-size: 25px; }
  .result-category-grid, .command-detail-grid { grid-template-columns: 1fr 1fr; }
  .result-category:last-child { grid-column: 1 / -1; }
}
/* SVG reference: compact dark workbench with a two-row header. */
.cloudstrm-shell {
  --cs-bg: #121218;
  --cs-surface: #19191f;
  --cs-surface-raised: #1f1f27;
  --cs-surface-inset: #101016;
  --cs-line: #2d2d38;
  --cs-line-strong: #393844;
  --cs-text: #f2f1f7;
  --cs-muted: #a3a0af;
  --cs-dim: #747181;
  --cs-primary: #7c4dff;
  --cs-primary-soft: #bcaeff;
  --cs-success: #68d7a2;
  --cs-warning: #f0c276;
  --cs-danger: #ff8a9a;
  --cs-info: #82c8ff;
  background: #0d0d12;
  color: var(--cs-text);
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
  min-height: 100vh;
}

.shell-frame {
  background: var(--cs-bg);
  border: 1px solid var(--cs-line-strong);
  border-radius: 8px;
  box-shadow: 0 12px 36px rgba(0, 0, 0, .28);
  display: block;
  margin: 48px auto;
  max-width: 1344px;
  min-height: calc(100vh - 96px);
  overflow: hidden;
  width: calc(100% - 96px);
}

.shell-header {
  align-items: stretch;
  background: var(--cs-surface);
  display: block;
  min-height: 126px;
  padding: 0 24px;
}
.shell-header-top { min-height: 72px; }
.brand-lockup { gap: 12px; }
.brand-mark {
  background: #2b214e;
  border-color: #6655b8;
  color: var(--cs-primary-soft);
  flex-basis: 38px;
  height: 38px;
  width: 38px;
}
.brand-title { color: var(--cs-text); font-size: 16px; font-weight: 500; }
.brand-subtitle { color: var(--cs-dim); }
.brand-version { color: var(--cs-dim); font-size: 12px; margin-left: 0; }
.header-actions { gap: 12px; }
.runtime-indicator { color: var(--cs-muted); }
.runtime-indicator.is-active { color: var(--cs-success); }
.runtime-indicator.is-active .runtime-dot { background: var(--cs-success); box-shadow: none; }
.header-refresh { color: var(--cs-muted) !important; }
.header-refresh:hover { background: rgba(255, 255, 255, .06); }
.tab-bar {
  align-self: stretch;
  border-top: 1px solid rgba(45, 45, 56, .7);
  gap: 3px;
  height: 54px;
  margin-left: 0;
}
.tab-button {
  color: var(--cs-muted);
  font-size: 14px;
  font-weight: 500;
  min-height: 54px;
  padding: 0 20px;
}
.tab-button:hover { background: rgba(255, 255, 255, .025); color: var(--cs-text); }
.tab-button.is-active {
  background: #211b34;
  border-bottom-color: var(--cs-primary);
  color: var(--cs-primary-soft);
}
.shell-main { background: var(--cs-bg); min-width: 0; }
.shell-divider { background: var(--cs-line); }
.shell-content { max-width: none; padding: 42px 48px 52px; }
.shell-alert { margin-bottom: 22px; }
.page-intro { gap: 24px; margin-bottom: 24px; }
.eyebrow { color: var(--cs-primary-soft); }
h1 { color: var(--cs-text); font-size: 25px; font-weight: 500; }
.page-intro p { color: var(--cs-muted); font-size: 14px; }
.intro-meta { border-left-color: var(--cs-line); }
.meta-label { color: var(--cs-dim); }
.intro-meta strong { color: var(--cs-muted); }
.intro-actions > span { color: var(--cs-dim); }
.cloudstrm-shell :deep(.v-btn) {
  border-radius: 6px;
  letter-spacing: 0;
  text-transform: none;
}
.cloudstrm-shell :deep(.v-btn--variant-flat) { background: #8b6cf6; color: #17121f; }
.cloudstrm-shell :deep(.v-btn--variant-flat:hover) { background: #9b7eff; }
.cloudstrm-shell :deep(.v-btn--variant-outlined) { border-color: var(--cs-line-strong); color: var(--cs-muted); }
.cloudstrm-shell :deep(.v-btn--variant-tonal) { background: #2b2347; color: var(--cs-primary-soft); }

.runtime-banner {
  background: var(--cs-surface);
  border-color: var(--cs-line);
  gap: 12px;
  margin-bottom: 36px;
  min-height: 64px;
  padding: 12px 15px;
}
.runtime-banner.is-active { border-color: rgba(104, 215, 162, .28); }
.banner-icon { background: #21352d; color: var(--cs-success); }
.runtime-banner:not(.is-active) .banner-icon { background: #2b2a33; color: var(--cs-muted); }
.banner-copy strong { color: var(--cs-text); font-size: 14px; }
.banner-copy span { color: var(--cs-muted); font-size: 12px; }
.runtime-banner :deep(.v-chip) { background: #203b31 !important; color: var(--cs-success) !important; }
.runtime-banner:not(.is-active) :deep(.v-chip) { background: #292632 !important; color: var(--cs-muted) !important; }

.content-section { margin-bottom: 32px; }
.engine-metrics-section { border-top: 0; padding-top: 0; }
.section-heading { margin-bottom: 14px; }
h2 { color: var(--cs-text); font-size: 16px; font-weight: 500; }
.section-heading p { color: var(--cs-dim); font-size: 12px; }
.overview-refresh-state { color: var(--cs-dim); }
.overview-refresh-state.is-ready { color: var(--cs-primary-soft); }
.metric-grid { gap: 16px; margin-bottom: 36px; }
.metric-tile, .processing-overview-card, .command-progress-frame, .table-frame, .empty-state {
  background: var(--cs-surface);
  border-color: var(--cs-line);
  border-radius: 7px;
  box-shadow: none;
}
.metric-tile { min-height: 112px; padding: 18px 20px 16px; }
.metric-tile--accent { background: #1d1a29; border-color: #594b9e; }
.metric-heading { color: var(--cs-muted); }
.metric-heading .v-icon { color: var(--cs-dim); }
.metric-tile--accent .metric-heading .v-icon { color: var(--cs-primary-soft); }
.metric-tile strong { color: var(--cs-text); font-size: 28px; font-weight: 500; margin-top: 20px; }
.metric-tile--accent strong { color: var(--cs-primary-soft); }
.metric-caption { color: var(--cs-dim); }

.processing-overview-section {
  border-top: 1px solid var(--cs-line);
  margin-bottom: 36px;
  padding-top: 24px;
}
.processing-overview-grid { gap: 26px; grid-template-columns: 1.26fr 1fr; }
.processing-overview-card { min-height: 190px; padding: 24px; }
.processing-overview-card--strm { background: #1d1a29; border-color: #594b9e; }
.overview-card-heading { color: var(--cs-text); font-size: 16px; }
.overview-card-heading .v-icon { color: var(--cs-primary-soft); }
.overview-card-body { align-items: stretch; display: grid; gap: 24px; grid-template-columns: 1fr 1fr 1.1fr; margin-top: 18px; }
.overview-value-group { min-width: 0; }
.overview-value-group span { color: var(--cs-muted); display: block; font-size: 12px; }
.overview-value-group strong { color: var(--cs-text); display: block; font-size: 34px; font-weight: 500; line-height: 1; margin-top: 18px; }
.overview-consistency {
  align-content: center;
  border-left: 1px solid var(--cs-line);
  column-gap: 8px;
  display: grid;
  grid-template-columns: auto 1fr;
  min-height: 82px;
  padding-left: 26px;
}
.overview-consistency .v-icon { grid-row: 1 / span 2; }
.overview-consistency strong { font-size: 14px; font-weight: 500; }
.overview-consistency span { color: var(--cs-muted); font-size: 12px; grid-column: 2; margin-top: 5px; }
.overview-consistency.is-consistent { color: var(--cs-success); }
.overview-consistency.is-inconsistent { color: var(--cs-warning); }
.overview-consistency.is-pending { color: var(--cs-warning); }
.overview-card-note { color: var(--cs-dim); display: block; font-size: 11px; margin-top: 22px; }
.processing-overview-card--side { gap: 14px; }
.overview-side-caption { color: var(--cs-dim); font-size: 12px; }
.overview-stat-row { grid-template-columns: minmax(150px, 1fr) auto auto; }
.overview-stat-label { color: var(--cs-text); }
.overview-stat-label .v-icon { color: var(--cs-dim); }
.overview-stat-row strong { color: var(--cs-muted); font-size: 14px; }
.overview-stat-completed { color: var(--cs-success) !important; }
.overview-stat-completed--subtitle { color: var(--cs-warning) !important; }
.cloudstrm-shell :deep(.v-progress-linear) { --v-theme-primary: 124, 77, 255; --v-theme-secondary: 45, 45, 56; --v-theme-success: 104, 215, 162; --v-theme-warning: 240, 194, 118; }

.command-progress-frame { padding: 18px 22px 20px; }
.full-scan-frame { padding: 18px 24px 20px; }
.full-scan-toolbar { gap: 14px; }
.scan-state, .status-chip { border-radius: 5px; }
.scan-state { border-color: var(--cs-line); color: var(--cs-muted); }
.scan-state--running, .scan-state--done { background: #203b31; border-color: #356a54; color: var(--cs-success); }
.scan-state--idle { background: #292632; color: var(--cs-dim); }
.full-scan-label, .full-scan-detail span, .full-scan-footer, .command-detail span { color: var(--cs-muted); }
.full-scan-detail strong, .command-detail strong { color: var(--cs-text); }
.command-detail { background: var(--cs-surface-inset); border-color: var(--cs-line); }
.result-summary-heading strong { color: var(--cs-text); }
.result-category { background: var(--cs-surface-inset); border-color: var(--cs-line); }
.result-category span { color: var(--cs-muted); }
.result-category--muted strong { color: var(--cs-muted); }
.result-category--neutral strong { color: var(--cs-text); }
.result-category--info strong { color: var(--cs-info); }
.result-category--success strong { color: var(--cs-success); }
.result-category--danger strong, .danger-number { color: var(--cs-danger) !important; }
.stalled-warning { background: #36332b; border-color: #665d43; color: var(--cs-warning); }
.status-chip--active { background: #2b2347; border-color: #594b9e; color: var(--cs-primary-soft); }
.status-chip--success { background: #203b31; border-color: #356a54; color: var(--cs-success); }
.status-chip--danger { background: #482630; border-color: #703c4b; color: var(--cs-danger); }
.status-chip--muted { background: #292632; border-color: #4a4658; color: var(--cs-dim); }

.status-table { color: var(--cs-text); min-width: 620px; }
.status-table :deep(th) { background: #1f1f27; border-bottom-color: var(--cs-line) !important; color: var(--cs-dim) !important; }
.status-table :deep(td) { border-bottom-color: var(--cs-line) !important; color: var(--cs-muted); }
.status-table :deep(tbody tr:hover) { background: #1b1b22; }
.result-inline--muted { background: #292632; color: var(--cs-muted); }
.result-inline--neutral { background: #2a2931; color: var(--cs-text); }
.result-inline--info { background: #203747; color: var(--cs-info); }
.result-inline--success { background: #203b31; color: var(--cs-success); }
.result-inline--danger { background: #482630; color: var(--cs-danger); }
.section-count { background: var(--cs-surface); border-color: var(--cs-line); color: var(--cs-dim); }
.section-count.has-items { border-color: #703c4b; color: var(--cs-danger); }
.empty-icon { background: #292632; border-color: var(--cs-line); color: var(--cs-muted); }
.empty-icon--success { background: #203b31; border-color: #356a54; color: var(--cs-success); }
.empty-state strong { color: var(--cs-text); }
.empty-state span { color: var(--cs-dim); }

@media (max-width: 900px) {
  .shell-frame { margin: 24px; min-height: calc(100vh - 48px); width: calc(100% - 48px); }
  .shell-content { padding: 36px 28px 44px; }
  .processing-overview-grid { grid-template-columns: 1fr; }
  .processing-overview-card--side { min-height: 190px; }
}

@media (max-width: 700px) {
  .shell-frame { border-radius: 0; margin: 0; min-height: 100vh; width: 100%; }
  .shell-header { min-height: 112px; padding: 0 16px; }
  .shell-header-top { min-height: 64px; }
  .brand-subtitle, .brand-version, .runtime-indicator { display: none; }
  .brand-title { font-size: 15px; }
  .brand-mark { flex-basis: 34px; height: 34px; width: 34px; }
  .tab-bar, .tab-button { height: 48px; min-height: 48px; }
  .tab-button { flex: 1; justify-content: center; padding: 0 12px; }
  .shell-content { padding: 28px 16px 40px; }
  .page-intro { align-items: flex-start; display: flex; flex-direction: column; gap: 16px; }
  .intro-actions { align-items: stretch; margin-left: 0; width: 100%; }
  .intro-actions :deep(.v-btn) { width: 100%; }
  .intro-actions > span { text-align: left; }
  .intro-meta { border-left: 0; border-top: 1px solid var(--cs-line); padding-left: 0; padding-top: 10px; width: 100%; }
  .runtime-banner { align-items: flex-start; margin-bottom: 28px; padding: 16px; }
  .banner-copy span { white-space: normal; }
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .processing-overview-card { padding: 18px; }
  .overview-card-body { gap: 18px; grid-template-columns: 1fr 1fr; }
  .overview-consistency { border-left: 0; border-top: 1px solid var(--cs-line); grid-column: 1 / -1; min-height: 58px; padding: 14px 0 0; }
  .overview-card-note { margin-top: 16px; }
  .overview-stat-row { grid-template-columns: minmax(0, 1fr) auto; }
  .overview-stat-completed { grid-column: 2; grid-row: 1; }
  .full-scan-toolbar { align-items: flex-start; flex-wrap: wrap; }
  .full-scan-state { margin-left: 0; width: 100%; }
  .full-scan-details, .command-detail-grid { grid-template-columns: 1fr; }
  .command-detail--path { grid-column: auto; }
  .full-scan-footer { align-items: flex-start; flex-direction: column; gap: 4px; }
  .result-category-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .result-category:last-child { grid-column: 1 / -1; }
  .dashboard-columns { gap: 24px; grid-template-columns: 1fr; }
}

@media (max-width: 420px) {
  .metric-grid { gap: 9px; }
  .metric-tile { min-height: 116px; padding: 14px; }
  .metric-tile strong { font-size: 25px; }
  .overview-card-body { gap: 12px; }
  .overview-value-group strong { font-size: 29px; }
}

.cloudstrm-shell :deep(.v-btn.bg-primary.v-btn--variant-flat) {
  background: #8b6cf6 !important;
  background-color: #8b6cf6 !important;
  color: #17121f !important;
}

.cloudstrm-shell :deep(.v-btn.bg-primary.v-btn--variant-flat:hover:not(:disabled)) {
  background: #9b7eff !important;
  background-color: #9b7eff !important;
}

.cloudstrm-shell :deep(.v-btn.bg-primary.v-btn--variant-flat:disabled),
.cloudstrm-shell :deep(.v-btn.bg-primary.v-btn--variant-flat.v-btn--disabled) {
  background: #594b9e !important;
  background-color: #594b9e !important;
  color: #c7bdf0 !important;
}
</style>
