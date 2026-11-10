<script setup>
import { ref } from 'vue'
import { runEval } from '../api.js'

const report = ref(null)
const loading = ref(false)
const error = ref('')
const expanded = ref(null)

async function run() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    report.value = await runEval()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function toggle(caseId) {
  expanded.value = expanded.value === caseId ? null : caseId
}
</script>

<template>
  <div style="max-width: 960px">
    <div style="display: flex; align-items: center; justify-content: space-between">
      <div>
        <h2 class="page-title">评测与护栏平台</h2>
        <p class="page-desc">遍历 dataset.jsonl 调用客服 Agent，护栏检测（死循环 / 越权）+ 相似度评分</p>
      </div>
      <button class="btn" :disabled="loading" @click="run">
        <span v-if="loading" class="spin"></span>
        {{ loading ? '评测运行中（约 1 分钟）' : '运行评测' }}
      </button>
    </div>

    <div v-if="error" class="error-banner" style="margin-top: 16px">{{ error }}</div>

    <template v-if="report">
      <div class="metric-grid" style="margin-top: 20px">
        <div class="metric-card">
          <div class="metric-label">总用例</div>
          <div class="metric-value">{{ report.total_cases }}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">通过率</div>
          <div class="metric-value" :style="{ color: report.summary.pass_rate >= 0.6 ? 'var(--ok)' : 'var(--warn)' }">
            {{ (report.summary.pass_rate * 100).toFixed(0) }}%
          </div>
        </div>
        <div class="metric-card">
          <div class="metric-label">平均相似度</div>
          <div class="metric-value">{{ report.summary.avg_similarity.toFixed(2) }}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">死循环触发</div>
          <div class="metric-value" :style="{ color: report.summary.guardrail_violations.infinite_loop_triggers ? 'var(--danger)' : 'var(--ok)' }">
            {{ report.summary.guardrail_violations.infinite_loop_triggers }}
          </div>
        </div>
        <div class="metric-card">
          <div class="metric-label">越权触发</div>
          <div class="metric-value" :style="{ color: report.summary.guardrail_violations.unauthorized_tool_triggers ? 'var(--danger)' : 'var(--ok)' }">
            {{ report.summary.guardrail_violations.unauthorized_tool_triggers }}
          </div>
        </div>
      </div>

      <div class="card" style="margin-top: 16px; padding: 0; overflow: hidden">
        <table style="width: 100%; border-collapse: collapse; font-size: 13px">
          <thead>
            <tr style="color: var(--text-dim); text-align: left">
              <th style="padding: 12px 16px; font-weight: 500">用例</th>
              <th style="padding: 12px 16px; font-weight: 500">相似度</th>
              <th style="padding: 12px 16px; font-weight: 500">结果</th>
              <th style="padding: 12px 16px; font-weight: 500">护栏</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="c in report.cases" :key="c.case_id"
              style="border-top: 1px solid var(--border); cursor: pointer"
              @click="toggle(c.case_id)"
            >
              <td style="padding: 12px 16px">
                <div style="font-family: var(--mono); color: var(--accent); font-size: 12px">{{ c.case_id }}</div>
                <div style="color: var(--text-dim); margin-top: 4px; max-width: 380px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ c.input }}</div>
              </td>
              <td style="padding: 12px 16px; min-width: 130px">
                <div style="display: flex; align-items: center; gap: 8px">
                  <div style="flex: 1; height: 5px; background: var(--bg-soft); border-radius: 3px; overflow: hidden">
                    <div :style="{ width: (c.similarity * 100) + '%', height: '100%', background: c.similarity >= 0.5 ? 'var(--ok)' : 'var(--warn)' }"></div>
                  </div>
                  <span style="font-family: var(--mono); font-size: 12px">{{ c.similarity.toFixed(2) }}</span>
                </div>
              </td>
              <td style="padding: 12px 16px">
                <span class="badge" :class="c.passed ? 'ok' : 'danger'">{{ c.passed ? '通过' : '未过' }}</span>
              </td>
              <td style="padding: 12px 16px">
                <span v-if="c.guardrails.infinite_loop" class="badge danger" style="margin-right: 6px">死循环</span>
                <span v-if="c.guardrails.unauthorized_tool" class="badge danger" style="margin-right: 6px">越权</span>
                <span v-if="!c.guardrails.infinite_loop && !c.guardrails.unauthorized_tool" class="badge ok">无缺陷</span>
              </td>
            </tr>
            <tr v-if="expanded" style="border-top: 1px solid var(--border)">
              <td colspan="4" style="padding: 14px 16px; background: var(--bg-soft)">
                <div style="font-size: 12px; color: var(--text-dim); margin-bottom: 8px">Agent 回复</div>
                <p style="font-size: 13px; line-height: 1.6; margin-bottom: 14px">{{ report.cases.find((x) => x.case_id === expanded).actual_output }}</p>
                <div style="font-size: 12px; color: var(--text-dim); margin-bottom: 6px">运行轨迹 (Trace)</div>
                <pre style="font-family: var(--mono); font-size: 12px; color: var(--cyan); overflow-x: auto">{{ JSON.stringify(report.cases.find((x) => x.case_id === expanded).trace, null, 2) }}</pre>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p style="margin-top: 10px; font-size: 12px; color: var(--text-dim)">点击任意行展开 Agent 回复与工具调用轨迹</p>
    </template>

    <div v-else-if="!loading" class="card" style="margin-top: 20px">
      <div class="empty">尚未运行评测，点击右上角「运行评测」开始</div>
    </div>
  </div>
</template>
