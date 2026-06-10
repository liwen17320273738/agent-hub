"""
Image Generation (Nano Banana Pro / Gemini 3 Pro Image)
========================================================

Self-contained, server-safe image generation used by the visual pipeline
(UI mockups + architecture diagrams). Replaces the previous dependency on the
WorkBuddy desktop skill script (``~/.workbuddy/skills/nano-banana-pro``) and
its ``uv run`` subprocess bootstrap.

Calls the Gemini ``gemini-3-pro-image-preview`` model directly via the
``google-genai`` SDK in-process. All failures are swallowed and return
``None`` so callers can gracefully fall back to HTML/Mermaid output.

API key resolution order:
    1. explicit ``api_key`` argument
    2. ``settings.google_api_key`` (from ``GOOGLE_API_KEY`` in .env)
    3. ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY`` environment variables
"""

from __future__ import annotations

import asyncio
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

IMAGE_MODEL = "gemini-3-pro-image-preview"
_VALID_RESOLUTIONS = {"1K", "2K", "4K"}


def resolve_api_key(api_key: Optional[str] = None) -> str:
    """Resolve the Gemini API key from arg → settings → environment."""
    if api_key:
        return api_key.strip()
    try:
        from app.config import settings as _cfg

        if (_cfg.google_api_key or "").strip():
            return _cfg.google_api_key.strip()
    except Exception:
        pass
    return (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    ).strip()


def sdk_available() -> bool:
    """Return True when the google-genai SDK + Pillow are importable."""
    try:
        import google.genai  # noqa: F401
        import PIL  # noqa: F401

        return True
    except Exception:
        return False


def is_available(api_key: Optional[str] = None) -> bool:
    """Return True when both an API key and the SDK are available."""
    return bool(resolve_api_key(api_key)) and sdk_available()


def _generate_image_sync(
    prompt: str,
    out_path: str,
    *,
    api_key: str,
    resolution: str = "2K",
    aspect_ratio: str = "1:1",
    input_image_path: Optional[str] = None,
) -> Optional[str]:
    """Blocking image generation. Returns the saved PNG path or None."""
    try:
        from google import genai
        from google.genai import types
        from PIL import Image as PILImage
    except Exception as e:  # pragma: no cover - import guard
        logger.warning("[image-gen] google-genai/Pillow not installed: %s", e)
        return None

    resolution = resolution if resolution in _VALID_RESOLUTIONS else "2K"

    try:
        client = genai.Client(api_key=api_key)

        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # The generate_content ImageConfig only supports aspect_ratio (resolution
        # control is Imagen-only), so fold the desired resolution into the prompt.
        full_prompt = f"{prompt}\n\nRender in {resolution} high resolution."
        if input_image_path and os.path.exists(input_image_path):
            contents = [PILImage.open(input_image_path), full_prompt]
        else:
            contents = full_prompt

        response = client.models.generate_content(
            model=IMAGE_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
            ),
        )

        for part in getattr(response, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline is None:
                continue
            data = inline.data
            if isinstance(data, str):
                import base64

                data = base64.b64decode(data)
            image = PILImage.open(BytesIO(data))
            # Gemini returns JPEG by default — normalise to RGB and save as PNG.
            if image.mode == "RGBA":
                rgb = PILImage.new("RGB", image.size, (255, 255, 255))
                rgb.paste(image, mask=image.split()[3])
                rgb.save(str(out), "PNG")
            elif image.mode == "RGB":
                image.save(str(out), "PNG")
            else:
                image.convert("RGB").save(str(out), "PNG")
            logger.info("[image-gen] Image saved: %s", out)
            return str(out)

        logger.warning("[image-gen] No image part in Gemini response")
        return None
    except Exception as e:
        logger.warning("[image-gen] Generation failed: %s", e)
        return None


async def generate_image(
    prompt: str,
    out_path: str,
    *,
    api_key: Optional[str] = None,
    resolution: str = "2K",
    aspect_ratio: str = "1:1",
    input_image_path: Optional[str] = None,
) -> Optional[str]:
    """Generate an image via Gemini (Nano Banana Pro). Returns PNG path or None.

    Runs the blocking SDK call in a worker thread so it is safe to await from
    the async pipeline. Never raises — returns ``None`` on any failure so the
    caller can fall back to HTML/Mermaid.
    """
    key = resolve_api_key(api_key)
    if not key:
        logger.info("[image-gen] No Gemini API key configured — skipping image generation")
        return None

    return await asyncio.to_thread(
        _generate_image_sync,
        prompt,
        out_path,
        api_key=key,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        input_image_path=input_image_path,
    )
