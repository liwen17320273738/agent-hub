"""Unit tests for pen_generator.py — Pencil .pen file generation."""
from __future__ import annotations

import json
import os
import tempfile
import uuid

from app.services.pen_generator import (
    _extract_color_tokens,
    _extract_font_tokens,
    _extract_spacing_tokens,
    _slugify_filename,
    _build_pen_document,
    generate_pen_file,
    check_pen_resources,
)


class TestSlugify:
    def test_slugify_basic(self) -> None:
        assert _slugify_filename("Hello World") == "hello-world"

    def test_slugify_chinese(self) -> None:
        result = _slugify_filename("用户登录系统")
        assert "用户登录系统" in result

    def test_slugify_special_chars(self) -> None:
        result = _slugify_filename("My Project!! (v2)")
        # Multiple non-word chars are collapsed into single hyphens
        assert "project" in result
        assert "v2" in result

    def test_slugify_empty_fallback(self) -> None:
        assert _slugify_filename("!@#$%", max_len=10) == "design"

    def test_slugify_truncation(self) -> None:
        long = "a" * 100
        result = _slugify_filename(long, max_len=20)
        assert len(result) <= 20


class TestExtractColorTokens:
    def test_extract_primary_color(self) -> None:
        spec = "主色：#4F46E5"
        tokens = _extract_color_tokens(spec)
        assert "color-primary" in tokens
        assert tokens["color-primary"] == "#4F46E5"

    def test_extract_rgba_color(self) -> None:
        spec = "主色：rgba(79, 70, 229, 1)"
        tokens = _extract_color_tokens(spec)
        assert "color-primary" in tokens

    def test_extract_secondary_color(self) -> None:
        spec = "辅色: #10B981"
        tokens = _extract_color_tokens(spec)
        assert "color-secondary" in tokens
        assert tokens["color-secondary"] == "#10B981"

    def test_extract_background(self) -> None:
        spec = "background: #FFFFFF"
        tokens = _extract_color_tokens(spec)
        assert "color-background" in tokens

    def test_extract_text_color(self) -> None:
        spec = "文字色：#333333"
        tokens = _extract_color_tokens(spec)
        assert "color-text" in tokens

    def test_extract_accent(self) -> None:
        spec = "accent: #F59E0B"
        tokens = _extract_color_tokens(spec)
        assert "color-accent" in tokens

    def test_no_colors(self) -> None:
        spec = "没有颜色的规格说明书"
        tokens = _extract_color_tokens(spec)
        assert tokens == {}

    def test_multiple_colors(self) -> None:
        spec = "主色：#4F46E5\n辅色: #10B981\n背景色:#F5F5F5"
        tokens = _extract_color_tokens(spec)
        assert len(tokens) >= 3


class TestExtractFontTokens:
    def test_font_family(self) -> None:
        spec = "字体：Inter, sans-serif"
        tokens = _extract_font_tokens(spec)
        assert tokens.get("font-family") == "Inter, sans-serif"

    def test_font_family_english(self) -> None:
        spec = "font-family: PingFang SC, 'Microsoft YaHei'"
        tokens = _extract_font_tokens(spec)
        assert "font-family" in tokens

    def test_body_font_size(self) -> None:
        spec = "正文字号：16"
        tokens = _extract_font_tokens(spec)
        assert tokens.get("font-size-body") == "16"

    def test_heading_font_size(self) -> None:
        spec = "标题字号: 24"
        tokens = _extract_font_tokens(spec)
        assert tokens.get("font-size-heading") == "24"

    def test_no_font_info(self) -> None:
        spec = "这是一个纯文字文档"
        tokens = _extract_font_tokens(spec)
        assert tokens == {}


class TestExtractSpacingTokens:
    def test_spacing(self) -> None:
        spec = "间距：16"
        tokens = _extract_spacing_tokens(spec)
        assert tokens.get("spacing") == "16"

    def test_border_radius(self) -> None:
        spec = "圆角：8"
        tokens = _extract_spacing_tokens(spec)
        assert tokens.get("border-radius") == "8"

    def test_no_spacing(self) -> None:
        spec = "无间距信息"
        tokens = _extract_spacing_tokens(spec)
        assert tokens == {}


class TestBuildPenDocument:
    def test_basic_structure(self) -> None:
        doc = _build_pen_document("Test Project", {"color-primary": "#4F46E5"}, "")
        assert doc["version"] == "1.0"
        assert doc["project"] == "Test Project"
        assert "created_at" in doc
        assert "variables" in doc
        assert "nodes" in doc

    def test_variables_created(self) -> None:
        tokens = {
            "color-primary": "#4F46E5",
            "color-background": "#FFFFFF",
            "font-family": "Inter",
            "font-size-body": "16",
            "font-size-heading": "24",
            "spacing": "16",
            "border-radius": "8",
        }
        doc = _build_pen_document("Proj", tokens, "")
        var_names = [v["name"] for v in doc["variables"]]
        assert "颜色/primary" in var_names
        assert "字体/正文字号" in var_names
        assert "字体/标题字号" in var_names

    def test_artboard_structure(self) -> None:
        doc = _build_pen_document("My App", {}, "")
        nodes = doc["nodes"]
        assert len(nodes) == 1
        artboard = nodes[0]
        assert artboard["id"] == "main-screen"
        assert artboard["type"] == "frame"
        assert artboard["width"] == 1440
        assert artboard["height"] == 900
        children = artboard.get("children", [])
        assert len(children) >= 3  # header, content, footer

    def test_project_name_in_header(self) -> None:
        doc = _build_pen_document("My Dashboard", {}, "")
        header = doc["nodes"][0]["children"][0]
        logo = header["children"][0]
        assert logo["content"] == "My Dashboard"


class TestGeneratePenFile:
    def test_generates_pen_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_pen_file(
                task_id=str(uuid.uuid4()),
                task_worktree=tmpdir,
                design_spec="主色：#4F46E5\n正文字号：16",
                project_name="Test Project",
            )
            assert result is not None
            assert result["ok"] is True
            assert "penPath" in result
            assert result["penPath"].endswith(".pen")
            assert os.path.exists(result["penPath"])
            pen_dir = os.path.join(tmpdir, "pen_designs")
            assert os.path.isdir(pen_dir)

    def test_pen_file_is_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_pen_file(
                task_id=str(uuid.uuid4()),
                task_worktree=tmpdir,
                design_spec="",
                project_name="Test",
            )
            assert result and result["ok"]
            with open(result["penPath"], "r", encoding="utf-8") as f:
                doc = json.load(f)
            assert doc["version"] == "1.0"
            assert len(doc["nodes"]) == 1

    def test_no_worktree_returns_none(self) -> None:
        result = generate_pen_file(
            task_id=str(uuid.uuid4()),
            task_worktree="",
            design_spec="test",
            project_name="Test",
        )
        # Returns None when no worktree provided
        assert result is None

    def test_with_design_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tokens = {
                "colors": {"primary": "#FF0000", "background": "#000000"},
                "typography": {"body_size": "14", "heading_size": "20"},
            }
            result = generate_pen_file(
                task_id=str(uuid.uuid4()),
                task_worktree=tmpdir,
                design_spec="",
                project_name="Token Test",
                design_tokens=tokens,
            )
            assert result and result["ok"]
            with open(result["penPath"], "r", encoding="utf-8") as f:
                doc = json.load(f)
            var_names = [v["name"] for v in doc["variables"]]
            assert "颜色/primary" in var_names or "字体/正文字号" in var_names
            assert "字体/正文字号" in var_names



class TestCheckPenResources:
    def test_always_true(self) -> None:
        assert check_pen_resources() is True
