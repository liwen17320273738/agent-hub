<template>
  <div class="voice-input">
    <div class="voice-btn-group">
      <!-- 主按钮：录音 -->
      <div
        class="voice-trigger"
        :class="{ recording: isRecording, processing: isProcessing }"
        @click="handleRecordToggle"
        :title="isRecording ? '点击停止录音' : '点击开始录音'"
      >
        <div class="mic-icon">
          <svg v-if="!isRecording && !isProcessing" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
            <line x1="12" x2="12" y1="19" y2="22"/>
          </svg>
          <div v-else-if="isRecording" class="recording-pulse">
            <span></span><span></span><span></span>
          </div>
          <div v-else class="spinner"></div>
        </div>
      </div>

      <!-- 分割线 + 文件上传按钮 -->
      <div class="voice-divider"></div>
      <div
        class="voice-trigger upload-trigger"
        :class="{ processing: isUploading }"
        @click="triggerFileUpload"
        title="上传音频文件进行转录"
      >
        <div class="mic-icon">
          <svg v-if="!isUploading" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/>
            <line x1="12" x2="12" y1="3" y2="15"/>
          </svg>
          <div v-else class="spinner"></div>
        </div>
      </div>
    </div>

    <span class="voice-label">{{ statusText }}</span>

    <!-- 隐藏的文件选择器 -->
    <input
      ref="fileInput"
      type="file"
      accept="audio/*,.wav,.mp3,.m4a,.ogg,.flac,.webm,.aac,.aiff,.wma,.opus,.amr,.caf,.m4a"
      style="display: none"
      @change="handleFileSelected"
    />

    <!-- 转录结果弹窗 -->
    <div v-if="transcription" class="transcription-modal" @click.self="transcription = null">
      <div class="transcription-card">
        <div class="card-header">
          <h3>{{ uploadMode === 'file' ? '文件转录结果' : '语音转录结果' }}</h3>
          <button class="close-btn" @click="transcription = null">&times;</button>
        </div>
        <div class="card-body">
          <div class="meta">
            <span v-if="transcription.speakerCount" class="badge">{{ transcription.speakerCount }} 位说话人</span>
            <span v-if="transcription.durationS" class="badge">{{ transcription.durationS }}秒</span>
            <span v-if="transcription.segmentCount" class="badge">{{ transcription.segmentCount }} 段</span>
            <span v-if="transcription.taskCreated" class="badge success">已创建任务</span>
          </div>
          <div class="text-content">{{ transcription.fullText || '(无识别文字)' }}</div>
        </div>
        <div class="card-footer">
          <button class="btn btn-primary" @click="createTask" :disabled="!transcription?.fullText">
            🚀 创建任务
          </button>
          <button class="btn btn-primary outline" @click="refillInput" :disabled="!transcription?.fullText">
            📝 填入输入框
          </button>
          <button class="btn btn-secondary" @click="copyText" :disabled="!transcription?.fullText">
            📋 复制
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { apiFetch } from '@/services/api'

/* ── State ── */
const isRecording = ref(false)
const isProcessing = ref(false)
const isUploading = ref(false)
const transcription = ref<any>(null)
const mediaRecorder = ref<MediaRecorder | null>(null)
const audioChunks = ref<Blob[]>([])
const statusText = ref('语音输入')
const fileInput = ref<HTMLInputElement | null>(null)
const uploadMode = ref<'record' | 'file'>('record')

/* ── Recording ── */
function handleRecordToggle() {
  if (isProcessing.value || isUploading.value) return
  if (!isRecording.value) startRecording()
  else stopRecording()
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    mediaRecorder.value = new MediaRecorder(stream, {
      mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm',
    })
    audioChunks.value = []

    mediaRecorder.value.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.value.push(e.data)
    }

    mediaRecorder.value.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop())
      await uploadAudio(new Blob(audioChunks.value, { type: 'audio/webm' }), 'voice.webm', 'record')
    }

    mediaRecorder.value.start()
    isRecording.value = true
    uploadMode.value = 'record'
    statusText.value = '正在录音...'
  } catch (err) {
    statusText.value = '麦克风不可用'
    setTimeout(() => { statusText.value = '语音输入' }, 2500)
  }
}

function stopRecording() {
  if (mediaRecorder.value && mediaRecorder.value.state === 'recording') {
    mediaRecorder.value.stop()
    isRecording.value = false
    isProcessing.value = true
    statusText.value = '正在识别...'
  }
}

/* ── File Upload ── */
function triggerFileUpload() {
  if (isRecording.value || isProcessing.value || isUploading.value) return
  fileInput.value?.click()
}

async function handleFileSelected(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  // Validate file type (extension + MIME)
  const audioExtensions = ['.wav', '.mp3', '.m4a', '.ogg', '.flac', '.webm', '.aac', '.aiff', '.wma', '.opus', '.amr', '.caf']
  const nameLower = file.name.toLowerCase()
  const byExtension = audioExtensions.some((ext) => nameLower.endsWith(ext))
  // Some systems report audio/*, some report video/mp4 for m4a, some report empty type
  const byMime = !file.type || file.type.startsWith('audio/') || file.type === 'video/mp4' || file.type === 'video/webm'
  if (!byExtension && !byMime) {
    statusText.value = `不支持的格式: ${file.name.split('.').pop()?.toUpperCase() || '未知'}`
    setTimeout(() => { statusText.value = '语音输入' }, 2500)
    target.value = ''
    return
  }

  // File size check (max 50MB)
  if (file.size > 50 * 1024 * 1024) {
    statusText.value = '文件过大（最大50MB）'
    setTimeout(() => { statusText.value = '语音输入' }, 2500)
    target.value = ''
    return
  }

  isUploading.value = true
  uploadMode.value = 'file'
  statusText.value = `正在上传 ${file.name.slice(0, 20)}...`

  await uploadAudio(file, file.name, 'file')
  isUploading.value = false
  target.value = '' // reset for re-upload
}

/* ── Shared Upload Logic ── */
async function uploadAudio(blob: Blob, filename: string, mode: 'record' | 'file') {
  const formData = new FormData()
  formData.append('audio', blob, filename)

  try {
    // apiFetch auto-detects FormData body and skips Content-Type,
    // letting browser set multipart/form-data with correct boundary.
    const result = await apiFetch('/gateway/vibevoice/transcribe', {
      method: 'POST',
      body: formData,
    })
    if (result.ok && result.transcription) {
      transcription.value = result.transcription
      statusText.value = mode === 'file' ? '✅ 文件识别完成' : '✅ 识别完成'
    } else {
      statusText.value = '❌ 识别失败'
    }
  } catch (err) {
    statusText.value = mode === 'file' ? '❌ 文件上传失败' : '❌ 请求失败'
    console.error('[voice] transcription error:', err)
  } finally {
    isProcessing.value = false
    setTimeout(() => { statusText.value = '语音输入' }, 3500)
  }
}

/* ── Transcription Actions ── */
const emit = defineEmits<{
  (e: 'taskCreated', text: string): void
  (e: 'fillInput', text: string): void
}>()

function createTask() {
  if (!transcription.value?.fullText) return
  const txt = encodeURIComponent(transcription.value.fullText.slice(0, 500))
  window.location.href = `/#/?voice=${txt}`
}

function refillInput() {
  if (!transcription.value?.fullText) return
  emit('fillInput', transcription.value.fullText)
  transcription.value = null
}

function copyText() {
  if (!transcription.value?.fullText) return
  navigator.clipboard.writeText(transcription.value.fullText)
  statusText.value = '✅ 已复制'
  setTimeout(() => { statusText.value = '语音输入' }, 2000)
}
</script>

<style scoped>
.voice-input {
  display: flex;
  align-items: center;
  gap: 8px;
}

.voice-btn-group {
  display: flex;
  align-items: center;
  border-radius: 100px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  overflow: hidden;
  transition: border-color 0.3s;
}

.voice-btn-group:hover {
  border-color: rgba(255, 255, 255, 0.2);
}

.voice-trigger {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  cursor: pointer;
  transition: all 0.3s ease;
  user-select: none;
}

.voice-trigger:hover {
  background: rgba(255, 255, 255, 0.08);
}

.voice-trigger.recording {
  background: rgba(239, 68, 68, 0.15);
  animation: pulse-bg 1.5s ease infinite;
}

.voice-trigger.processing {
  background: rgba(99, 102, 241, 0.12);
}

.voice-divider {
  width: 1px;
  height: 20px;
  background: rgba(255, 255, 255, 0.15);
}

.upload-trigger:hover {
  color: #818cf8;
}

.mic-icon {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.7);
}

.recording-pulse {
  display: flex;
  align-items: center;
  gap: 2px;
}

.recording-pulse span {
  width: 3px;
  height: 14px;
  background: #ef4444;
  border-radius: 2px;
  animation: pulse-bar 0.8s ease infinite;
}

.recording-pulse span:nth-child(2) { animation-delay: 0.2s; }
.recording-pulse span:nth-child(3) { animation-delay: 0.4s; }

@keyframes pulse-bar {
  0%, 100% { height: 6px; }
  50% { height: 16px; }
}

@keyframes pulse-bg {
  0%, 100% { background: rgba(239, 68, 68, 0.1); }
  50% { background: rgba(239, 68, 68, 0.22); }
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(99, 102, 241, 0.3);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.voice-label {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.7);
  white-space: nowrap;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Transcription Modal ── */
.transcription-modal {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(4px);
}

.transcription-card {
  width: 620px;
  max-width: 92vw;
  max-height: 82vh;
  background: #1a1a2e;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.card-header h3 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: #e2e8f0;
}

.close-btn {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.4);
  font-size: 22px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 8px;
  transition: all 0.2s;
  line-height: 1;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.card-body {
  padding: 20px 24px;
  overflow-y: auto;
  flex: 1;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 18px;
}

.badge {
  padding: 4px 12px;
  border-radius: 100px;
  background: rgba(99, 102, 241, 0.12);
  color: #818cf8;
  font-size: 12px;
  font-weight: 500;
}

.badge.success {
  background: rgba(34, 197, 94, 0.12);
  color: #22c55e;
}

.text-content {
  font-size: 14px;
  line-height: 1.75;
  color: rgba(255, 255, 255, 0.85);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 40vh;
  overflow-y: auto;
}

.card-footer {
  display: flex;
  gap: 10px;
  padding: 16px 24px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.btn {
  flex: 1;
  padding: 10px 16px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-primary {
  background: #6366f1;
  color: #fff;
}

.btn-primary:hover:not(:disabled) { background: #5558e6; }

.btn-primary.outline {
  background: transparent;
  border: 1px solid #6366f1;
  color: #818cf8;
}

.btn-primary.outline:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.1);
}

.btn-secondary {
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.75);
  border: 1px solid rgba(255, 255, 255, 0.1);
  flex: 0.6;
}

.btn-secondary:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
}
</style>
