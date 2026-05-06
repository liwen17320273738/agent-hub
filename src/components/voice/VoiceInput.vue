<template>
  <div class="voice-input">
    <div class="voice-trigger" @click="handleClick" :class="{ recording: isRecording, processing: isProcessing }">
      <div class="mic-icon">
        <svg v-if="!isRecording && !isProcessing" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
          <line x1="12" x2="12" y1="19" y2="22"/>
        </svg>
        <div v-else-if="isRecording" class="recording-pulse">
          <span></span><span></span><span></span>
        </div>
        <div v-else class="spinner"></div>
      </div>
      <span class="voice-label">{{ statusText }}</span>
    </div>

    <!-- Transcription result modal -->
    <div v-if="transcription" class="transcription-modal" @click.self="transcription = null">
      <div class="transcription-card">
        <div class="card-header">
          <h3>语音转录结果</h3>
          <button class="close-btn" @click="transcription = null">&times;</button>
        </div>
        <div class="card-body">
          <div class="meta">
            <span class="badge">{{ transcription.speakerCount }} 位说话人</span>
            <span class="badge">{{ transcription.durationS }}秒</span>
            <span class="badge">{{ transcription.segmentCount }} 段</span>
          </div>
          <div class="text-content">{{ transcription.fullText }}</div>
        </div>
        <div class="card-footer">
          <button class="btn btn-primary" @click="createTask">创建任务</button>
          <button class="btn btn-secondary" @click="copyText">复制文本</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { apiFetch } from '@/services/api'

const isRecording = ref(false)
const isProcessing = ref(false)
const transcription = ref<any>(null)
const mediaRecorder = ref<MediaRecorder | null>(null)
const audioChunks = ref<Blob[]>([])

const statusText = ref('语音输入')

function handleClick() {
  if (isProcessing.value) return

  if (!isRecording.value) {
    startRecording()
  } else {
    stopRecording()
  }
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    mediaRecorder.value = new MediaRecorder(stream, { mimeType: 'audio/webm' })
    audioChunks.value = []

    mediaRecorder.value.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.value.push(e.data)
    }

    mediaRecorder.value.onstop = async () => {
      stream.getTracks().forEach(t => t.stop())
      await uploadAudio()
    }

    mediaRecorder.value.start()
    isRecording.value = true
    statusText.value = '点击停止录音'
  } catch (err) {
    statusText.value = '麦克风不可用'
    setTimeout(() => { statusText.value = '语音输入' }, 2000)
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

async function uploadAudio() {
  const blob = new Blob(audioChunks.value, { type: 'audio/webm' })
  const formData = new FormData()
  formData.append('audio', blob, 'voice.webm')

  try {
    const result = await apiFetch('/gateway/vibevoice/transcribe', {
      method: 'POST',
      body: formData,
      headers: {}, // Let fetch set Content-Type for FormData
    })
    if (result.ok && result.transcription) {
      transcription.value = result.transcription
      statusText.value = '✅ 识别完成'
    } else {
      statusText.value = '❌ 识别失败'
    }
  } catch (err) {
    statusText.value = '❌ 请求失败'
    console.error('[voice] transcription error:', err)
  } finally {
    isProcessing.value = false
    setTimeout(() => { statusText.value = '语音输入' }, 3000)
  }
}

function createTask() {
  if (!transcription.value?.fullText) return
  // Navigate to dashboard with transcribed text pre-filled
  const txt = encodeURIComponent(transcription.value.fullText.slice(0, 500))
  window.location.href = `/#/?voice=${txt}`
}

function copyText() {
  if (!transcription.value?.fullText) return
  navigator.clipboard.writeText(transcription.value.fullText)
  statusText.value = '✅ 已复制'
}
</script>

<style scoped>
.voice-input {
  position: relative;
}

.voice-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: 100px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  cursor: pointer;
  transition: all 0.3s ease;
  user-select: none;
}

.voice-trigger:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.2);
}

.voice-trigger.recording {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.3);
  animation: pulse-border 1.5s ease infinite;
}

.voice-trigger.processing {
  background: rgba(99, 102, 241, 0.15);
  border-color: rgba(99, 102, 241, 0.3);
}

.mic-icon {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.recording-pulse {
  display: flex;
  align-items: center;
  gap: 3px;
}

.recording-pulse span {
  width: 4px;
  height: 16px;
  background: #ef4444;
  border-radius: 2px;
  animation: pulse-bar 0.8s ease infinite;
}

.recording-pulse span:nth-child(2) { animation-delay: 0.2s; }
.recording-pulse span:nth-child(3) { animation-delay: 0.4s; }

@keyframes pulse-bar {
  0%, 100% { height: 8px; }
  50% { height: 20px; }
}

@keyframes pulse-border {
  0%, 100% { border-color: rgba(239, 68, 68, 0.3); }
  50% { border-color: rgba(239, 68, 68, 0.7); }
}

.spinner {
  width: 20px;
  height: 20px;
  border: 2px solid rgba(99, 102, 241, 0.3);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.voice-label {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.8);
  white-space: nowrap;
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
  width: 600px;
  max-width: 90vw;
  max-height: 80vh;
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
  padding: 20px 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.card-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.close-btn {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.5);
  font-size: 24px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 8px;
  transition: all 0.2s;
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
  gap: 8px;
  margin-bottom: 16px;
}

.badge {
  padding: 4px 12px;
  border-radius: 100px;
  background: rgba(99, 102, 241, 0.15);
  color: #818cf8;
  font-size: 12px;
  font-weight: 500;
}

.text-content {
  font-size: 14px;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.85);
  white-space: pre-wrap;
}

.card-footer {
  display: flex;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.btn {
  flex: 1;
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary {
  background: #6366f1;
  color: #fff;
}

.btn-primary:hover { background: #5558e6; }

.btn-secondary {
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.1);
}
</style>
