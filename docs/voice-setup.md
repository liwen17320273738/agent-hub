# 语音识别功能设置指南

## 问题描述

如果你看到 "服务器内部错误" 或 "语音识别未启用" 的提示，说明 Whisper 语音识别模型未正确安装。

## 解决方案

### 1. 安装 Whisper

在后端目录安装 OpenAI Whisper：

```bash
cd backend
pip install openai-whisper
```

### 2. 安装音频处理依赖

Whisper 需要 ffmpeg 来处理音频文件：

**macOS:**
```bash
brew install ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install ffmpeg
```

**Windows:**
下载并安装 ffmpeg: https://ffmpeg.org/download.html

### 3. 重启后端服务

```bash
# 在项目根目录
make dev
```

或者

```bash
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

## 配置选项

在 `config.yaml` 或环境变量中配置：

```yaml
# 启用语音识别
vibevoice_enabled: true

# Whisper 模型大小（可选）
# 选项: tiny, base, small, medium, large
# 默认: medium（推荐，平衡速度和准确度）
whisper_model: medium
```

## 模型说明

| 模型 | 大小 | 速度 | 准确度 | 推荐场景 |
|------|------|------|--------|----------|
| tiny | ~39MB | 最快 | 较低 | 快速测试 |
| base | ~74MB | 快 | 一般 | 轻量使用 |
| small | ~244MB | 中等 | 良好 | 日常使用 |
| medium | ~769MB | 较慢 | 很好 | **推荐** |
| large | ~1.5GB | 慢 | 最好 | 高精度需求 |

## 硬件加速

- **Apple Silicon (M1/M2/M3)**: 自动使用 MPS 加速
- **NVIDIA GPU**: 需要安装 CUDA 和 PyTorch GPU 版本
- **CPU**: 自动回退到 CPU 模式

## 故障排查

### 错误: "Whisper is not installed"

```bash
pip install openai-whisper
```

### 错误: "ffmpeg not found"

安装 ffmpeg（见上方安装步骤）

### 错误: "识别超时"

- 尝试使用更小的模型（如 `small` 或 `base`）
- 确保音频文件不超过 50MB
- 检查 CPU/GPU 资源是否充足

### 模型下载慢

首次使用时，Whisper 会自动下载模型文件。如果下载慢：

1. 使用代理或 VPN
2. 手动下载模型文件到 `~/.cache/whisper/`
3. 使用更小的模型

## 测试

启动后端后，访问：

```
http://localhost:8000/gateway/vibevoice/status
```

应该返回：

```json
{
  "ok": true,
  "enabled": true,
  "available": true,
  "mode": "local"
}
```

## 使用

1. 点击麦克风图标开始录音
2. 再次点击停止录音
3. 等待转录完成
4. 查看转录结果并创建任务

或者：

1. 点击上传图标
2. 选择音频文件（支持 wav, mp3, m4a 等）
3. 等待转录完成
