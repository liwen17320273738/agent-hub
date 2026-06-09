"""Synthetic SSE output helpers — fallback must still produce chunk events."""
from app.services.sse import chunk_text_for_sse


def test_chunk_text_for_sse_splits_long_lines():
    text = "a" * 250 + "\nshort\n" + "b" * 80
    chunks = chunk_text_for_sse(text, chunk_size=120)
    assert len(chunks) >= 3
    assert "".join(chunks) == text


def test_chunk_text_for_sse_empty():
    assert chunk_text_for_sse("") == []


def test_chunk_text_for_sse_preserves_newlines():
    text = "## 标题\n\n第一段\n第二段"
    chunks = chunk_text_for_sse(text, chunk_size=120)
    assert "".join(chunks) == text
