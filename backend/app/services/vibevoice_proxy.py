"""
VibeVoice Proxy — Voice AI integration for Agent Hub
=====================================================

Wraps Microsoft VibeVoice ASR (Automatic Speech Recognition) model for
transcribing audio into structured text with speaker diarization.

Supports two modes:
    1. **HuggingFace Inference API** (default) — no local GPU needed.
    2. **Local Transformers** — requires ``transformers>=5.3.0`` + PyTorch
       with GPU (e.g. Mac M-series, CUDA).

Output format (parsed):
    [
        {"speaker": 0, "start": 0.0, "end": 15.43, "text": "..."},
        {"speaker": 1, "start": 15.43, "end": 30.0, "text": "..."},
    ]
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────

_HF_MODEL_ID = "microsoft/VibeVoice-ASR-HF"
_HF_INFERENCE_URL = f"https://api-inference.huggingface.co/models/{_HF_MODEL_ID}"

# ── Transcription Result ──────────────────────────────────────────────


class TranscriptionSegment:
    """A single transcribed segment with speaker and timing."""

    def __init__(self, speaker: int, start: float, end: float, text: str) -> None:
        self.speaker = speaker
        self.start = start
        self.end = end
        self.text = text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "speaker": self.speaker,
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "text": self.text,
        }


class TranscriptionResult:
    """Full transcription result."""

    def __init__(self, segments: List[TranscriptionSegment], duration_s: float) -> None:
        self.segments = segments
        self.duration_s = duration_s

    @property
    def full_text(self) -> str:
        return "\n".join(s.text for s in self.segments)

    @property
    def speaker_count(self) -> int:
        return len({s.speaker for s in self.segments})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "segments": [s.to_dict() for s in self.segments],
            "fullText": self.full_text,
            "durationS": round(self.duration_s, 1),
            "speakerCount": self.speaker_count,
            "segmentCount": len(self.segments),
        }


# ── Proxy Service ─────────────────────────────────────────────────────


class VibeVoiceProxy:
    """VibeVoice transcription service.

    Uses HuggingFace Inference API by default. Falls back to local
    model if ``force_local=True`` and transformers is available.
    """

    def __init__(self) -> None:
        self._model = None
        self._processor = None
        self._local_loaded = False

    # ── Public API ─────────────────────────────────────────────────────

    async def transcribe(
        self,
        audio_path: str,
        prompt: str = "",
        return_format: str = "parsed",
        timeout: float = 300.0,
    ) -> TranscriptionResult:
        """Transcribe an audio file to text.

        Args:
            audio_path: Local file path or HTTP(S) URL to audio.
            prompt: Optional context/hotwords to improve recognition.
            return_format: ``"parsed"`` (default), ``"transcription_only"``, or ``"raw"``.
            timeout: Maximum wait time in seconds.

        Returns:
            ``TranscriptionResult`` with segments and full text.
        """
        # Validate file exists (skip check for mock mode)
        if not self._hf_api_key and not self._local_loaded:
            duration = 0.0
            return TranscriptionResult(
                segments=[TranscriptionSegment(
                    speaker=0, start=0.0, end=0.0,
                    text=(
                        "[VibeVoice 未配置 HF_API_KEY，此为模拟输出]\n"
                        f"音频文件: {audio_path}\n"
                        "实际使用时请设置 HF_API_KEY 环境变量或 vibevoice_force_local=True"
                    ),
                )],
                duration_s=0.0,
            )

        if not os.path.exists(audio_path) and not audio_path.startswith(("http://", "https://")):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Detect duration
        duration = await self._detect_duration(audio_path)

        # Try local first, fall back to HF API
        if self._local_loaded or (
            settings.vibevoice_force_local and self._try_load_local()
        ):
            result = await self._transcribe_local(audio_path, prompt)
        else:
            result = await self._transcribe_api(audio_path, prompt, timeout)

        return TranscriptionResult(
            segments=result.get("segments", []),
            duration_s=duration,
        )

    async def transcribe_bytes(
        self,
        audio_data: bytes,
        filename: str = "audio.wav",
        prompt: str = "",
        timeout: float = 300.0,
    ) -> TranscriptionResult:
        """Transcribe raw audio bytes (e.g. from an upload)."""
        tmp = tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False)
        try:
            tmp.write(audio_data)
            tmp.flush()
            return await self.transcribe(tmp.name, prompt=prompt, timeout=timeout)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def is_available(self) -> bool:
        """Check if VibeVoice is available (API key set or local model loaded)."""
        if self._local_loaded:
            return True
        return bool(self._hf_api_key)

    # ── Internals: HuggingFace API ─────────────────────────────────────

    @property
    def _hf_api_key(self) -> str:
        return settings.hf_api_key or os.environ.get("HF_API_KEY", "")

    async def _transcribe_api(
        self,
        audio_path: str,
        prompt: str,
        timeout: float,
    ) -> Dict[str, Any]:
        """Transcribe via HuggingFace Inference API."""
        api_key = self._hf_api_key
        if not api_key:
            logger.warning("[vibevoice] No HF_API_KEY set, using mock mode")
            return self._mock_result(audio_path)

        # Read audio file
        if audio_path.startswith(("http://", "https://")):
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(audio_path)
                resp.raise_for_status()
                audio_data = resp.content
        else:
            with open(audio_path, "rb") as f:
                audio_data = f.read()

        headers = {
            "Authorization": f"Bearer {api_key}",
        }

        if prompt:
            headers["x-prompt"] = prompt

        started = time.monotonic()
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                _HF_INFERENCE_URL,
                headers=headers,
                content=audio_data,
            )

        elapsed = time.monotonic() - started
        logger.info("[vibevoice] API transcription in %.1fs (status=%d)", elapsed, resp.status_code)

        if resp.status_code == 503:
            # Model is loading on HF
            wait = float(resp.headers.get("x-wait-time", 20))
            logger.info("[vibevoice] Model loading, waiting %.0fs...", wait)
            await asyncio.sleep(wait)
            return await self._transcribe_api(audio_path, prompt, timeout)

        if resp.status_code != 200:
            raise RuntimeError(
                f"VibeVoice HF API error (HTTP {resp.status_code}): {resp.text[:500]}"
            )

        return self._parse_api_response(resp.json())

    def _parse_api_response(self, data: Any) -> Dict[str, Any]:
        """Parse HF API response into segments."""
        if isinstance(data, list):
            segments = []
            for item in data:
                if isinstance(item, dict):
                    segments.append({
                        "speaker": item.get("speaker", item.get("Speaker", 0)),
                        "start": item.get("start", item.get("Start", 0.0)),
                        "end": item.get("end", item.get("End", 0.0)),
                        "text": item.get("text", item.get("Content", item.get("text", ""))),
                    })
            return {"segments": segments}
        if isinstance(data, dict) and "text" in data:
            return {
                "segments": [{
                    "speaker": 0,
                    "start": 0.0,
                    "end": 0.0,
                    "text": data["text"],
                }]
            }
        return {"segments": [{"speaker": 0, "start": 0.0, "end": 0.0, "text": str(data)}]}

    # ── Internals: Local model ─────────────────────────────────────────

    def _try_load_local(self) -> bool:
        """Attempt to load the model locally (requires GPU + transformers)."""
        if self._local_loaded:
            return True
        try:
            import torch
            if not torch.cuda.is_available() and not (
                hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
            ):
                logger.info("[vibevoice] No GPU available, using HF API")
                return False
            from transformers import AutoProcessor, VibeVoiceAsrForConditionalGeneration
            logger.info("[vibevoice] Loading local model %s...", _HF_MODEL_ID)
            self._processor = AutoProcessor.from_pretrained(_HF_MODEL_ID)
            self._model = VibeVoiceAsrForConditionalGeneration.from_pretrained(
                _HF_MODEL_ID, device_map="auto",
            )
            self._local_loaded = True
            logger.info("[vibevoice] Local model loaded successfully")
            return True
        except ImportError as e:
            logger.info("[vibevoice] Cannot load locally (transformers not installed): %s", e)
            return False
        except Exception as e:
            logger.warning("[vibevoice] Failed to load local model: %s", e)
            return False

    async def _transcribe_local(
        self,
        audio_path: str,
        prompt: str,
    ) -> Dict[str, Any]:
        """Transcribe using locally loaded model."""
        if not self._local_loaded:
            return {"segments": []}

        import asyncio
        from transformers import pipeline

        loop = asyncio.get_event_loop()

        def _run():
            pipe = pipeline("any-to-any", model=self._model, processor=self._processor)
            chat = [{"role": "user", "content": [{"type": "audio", "path": audio_path}]}]
            if prompt:
                chat[0]["content"].insert(0, {"type": "text", "text": prompt})
            return pipe(text=chat, return_full_text=False)

        result = await loop.run_in_executor(None, _run)
        return {"segments": [{"speaker": 0, "start": 0.0, "end": 0.0, "text": str(result)}]}

    # ── Helpers ────────────────────────────────────────────────────────

    async def _detect_duration(self, audio_path: str) -> float:
        """Quick-detect audio duration (best-effort)."""
        try:
            import subprocess
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of", "csv=p=0", audio_path],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass
        return 0.0

    def _mock_result(self, audio_path: str) -> Dict[str, Any]:
        """Return a mock transcription when no API key is configured."""
        return {
            "segments": [{
                "speaker": 0,
                "start": 0.0,
                "end": 0.0,
                "text": (
                    "[VibeVoice 未配置 HF_API_KEY，此为模拟输出]\n"
                    f"音频文件: {audio_path}\n"
                    "实际使用时请设置 HF_API_KEY 环境变量或 vibevoice_force_local=True"
                ),
            }]
        }


# ── Singleton ─────────────────────────────────────────────────────────

_vibevoice_instance: Optional[VibeVoiceProxy] = None


def get_vibevoice() -> VibeVoiceProxy:
    """Get or create the VibeVoice proxy singleton."""
    global _vibevoice_instance
    if _vibevoice_instance is None:
        _vibevoice_instance = VibeVoiceProxy()
    return _vibevoice_instance
