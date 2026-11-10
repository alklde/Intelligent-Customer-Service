<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { createKbDocument, deleteKbDocument, listKbDocuments, reindexKb } from '../api.js'

const documents = ref([])
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const notice = ref('')
const form = reactive({ title: '', content: '', source: 'manual' })
const fileInput = ref(null)

async function load() {
  loading.value = true
  try {
    documents.value = await listKbDocuments()
    error.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function pickFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  if (!/\.(md|txt)$/i.test(file.name)) {
    error.value = '仅支持 .md / .txt 文本文件'
    event.target.value = ''
    return
  }
  if (file.size > 300 * 1024) {
    error.value = '文件不能超过 300KB'
    event.target.value = ''
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    form.content = String(reader.result || '')
    form.source = 'upload'
    if (!form.title) form.title = file.name.replace(/\.(md|txt)$/i, '')
    error.value = ''
  }
  reader.readAsText(file, 'utf-8')
}

async function submit() {
  if (submitting.value) return
  error.value = ''
  notice.value = ''
  submitting.value = true
  try {
    const doc = await createKbDocument({ ...form })
    notice.value = `文档已入库：${doc.title}（${doc.chunk_count} 个分块）`
    form.title = ''
    form.content = ''
    form.source = 'manual'
    if (fileInput.value) fileInput.value.value = ''
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    submitting.value = false
  }
}

async function remove(doc) {
  if (!window.confirm(`确认删除文档「${doc.title}」？该操作会同时清理向量索引。`)) return
  error.value = ''
  notice.value = ''
  try {
    await deleteKbDocument(doc.doc_id)
    notice.value = `已删除：${doc.title}`
    await load()
  } catch (e) {
    error.value = e.message
  }
}

async function rebuild() {
  if (!window.confirm('将按 Redis 文档全量重建向量索引，期间检索可能短暂不可用，继续？')) return
  error.value = ''
  notice.value = ''
  try {
    const result = await reindexKb()
    notice.value = `索引重建完成：${result.documents} 篇文档 / ${result.chunks} 个分块`
    await load()
  } catch (e) {
    error.value = e.message
  }
}

const fmtTime = (ts) => (ts ? new Date(Number(ts) * 1000).toLocaleString('zh-CN', { hour12: false }) : '-')

let timer = null
onMounted(() => {
  load()
  timer = setInterval(load, 10000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div style="max-width: 1080px">
    <div style="display: flex; align-items: center; justify-content: space-between">
      <div>
        <h2 class="page-title">知识库管理</h2>
        <p class="page-desc">仅管理员可维护；文档入库前会自动清洗、去重、分块并向量化</p>
      </div>
      <div style="display: flex; gap: 8px">
        <button class="btn ghost" :disabled="loading" @click="load">刷新</button>
        <button class="btn ghost" @click="rebuild">重建索引</button>
      </div>
    </div>

    <div v-if="error" class="error-banner" style="margin-top: 14px">{{ error }}</div>
    <div v-if="notice" class="notice-banner" style="margin-top: 14px">{{ notice }}</div>

    <div class="card" style="margin-top: 16px">
      <div style="font-weight: 600; font-size: 13px; margin-bottom: 10px">新增文档</div>
      <div class="form-row">
        <input v-model="form.title" class="input" maxlength="80" placeholder="文档标题（1-80 字）" />
        <select v-model="form.source" class="input" style="max-width: 160px">
          <option value="manual">手动录入</option>
          <option value="upload">文件导入</option>
          <option value="seed">初始语料</option>
        </select>
        <label class="btn ghost file-btn">
          选择文件
          <input ref="fileInput" type="file" accept=".md,.txt" hidden @change="pickFile" />
        </label>
      </div>
      <textarea v-model="form.content" class="textarea" style="margin-top: 10px; min-height: 160px" placeholder="粘贴或输入文档正文（支持 Markdown / 纯文本，20-50000 字）"></textarea>
      <div style="display: flex; align-items: center; gap: 10px; margin-top: 10px">
        <span style="font-size: 12px; color: var(--text-dim)">{{ form.content.length }} 字</span>
        <button class="btn" style="margin-left: auto" :disabled="submitting || !form.title.trim() || form.content.trim().length < 20" @click="submit">
          <span v-if="submitting" class="spin"></span> 入库
        </button>
      </div>
    </div>

    <div class="card" style="margin-top: 16px; padding: 0; overflow: hidden">
      <div style="padding: 14px 16px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border)">
        <strong style="font-size: 13px">文档列表</strong>
        <span class="badge info">{{ documents.length }} 篇</span>
      </div>
      <table class="kb-table">
        <thead>
          <tr><th>标题</th><th>来源</th><th>分块</th><th>更新时间</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="d in documents" :key="d.doc_id">
            <td>{{ d.title }}</td>
            <td><span class="badge info">{{ d.source }}</span></td>
            <td class="mono">{{ d.chunk_count }}</td>
            <td class="dim">{{ fmtTime(d.updated_at) }}</td>
            <td><button class="btn ghost" style="padding: 5px 12px; font-size: 12px" @click="remove(d)">删除</button></td>
          </tr>
          <tr v-if="!documents.length && !loading"><td colspan="5"><div class="empty">知识库暂无文档</div></td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.form-row { display: flex; gap: 10px; align-items: center; }
.file-btn { cursor: pointer; white-space: nowrap; }
.notice-banner { background: rgba(61, 214, 140, 0.10); border: 1px solid rgba(61, 214, 140, 0.35); color: var(--ok); padding: 10px 14px; border-radius: 9px; font-size: 13px; }
.kb-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.kb-table th { text-align: left; padding: 12px 16px; color: var(--text-dim); font-weight: 500; }
.kb-table td { padding: 11px 16px; border-top: 1px solid var(--border); }
.kb-table .mono { font-family: var(--mono); }
.kb-table .dim { color: var(--text-dim); font-size: 12px; }
</style>