"""
UI Visualizer + Architecture Diagram Generator
================================================

Generates visual artifacts from pipeline stage outputs:

UI/Design stages:
    1. ``ui_mockup`` — PNG image of the UI design (via Nano Banana Pro)
    2. ``ui_mockup_html`` — Interactive HTML prototype

Architecture stages:
    1. ``architecture_diagram`` — rendered diagram image (via Nano Banana Pro),
       with Mermaid-based HTML (overview / data flow / sequence) as fallback.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────

MOCKUP_DIR = "ui_mockups"
ARCH_DIR = "architecture_diagrams"


def _slugify_filename(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]", "-", (text or "").strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return (s[:max_len] or "mockup")


class UiVisualizer:
    """Generate visual UI mockups from pipeline design specs."""

    def __init__(self, workspace_root: str = "", task_worktree: str = "") -> None:
        self.workspace_root = workspace_root or os.environ.get(
            "WORKSPACE_ROOT", "/tmp/agent-hub-ui",
        )
        self.task_worktree = task_worktree or ""

    def _visual_out_dir(self, task_id: str, subdir: str) -> tuple[str, str]:
        """Return (absolute_out_dir, worktree_relative_prefix/subdir/)."""
        if self.task_worktree:
            abs_dir = os.path.join(self.task_worktree, subdir)
            rel_prefix = subdir
        else:
            abs_dir = os.path.join(self.workspace_root, task_id, subdir)
            rel_prefix = os.path.join(subdir)
        os.makedirs(abs_dir, exist_ok=True)
        return abs_dir, rel_prefix

    def _rel_path(self, rel_prefix: str, filename: str) -> str:
        return f"{rel_prefix}/{filename}".replace("\\", "/")

    # ── Resource Check (Phase 5, Task 5.1) ─────────────────────────────

    async def check_design_resources(self) -> Dict[str, Any]:
        """Check availability of all visual resource channels for designer stage.

        Returns:
            ``{"ok": bool, "channels": {name: available|reason}, "fallback": [...]}``
        """
        channels: Dict[str, Any] = {}
        fallbacks: List[str] = []

        # 1. OpenAI Images (image_gen_tool)
        openai_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        if openai_key:
            channels["openai_images"] = {"available": True, "model": os.environ.get("OPENAI_IMAGE_MODEL", "dall-e-3")}
        else:
            channels["openai_images"] = {"available": False, "reason": "OPENAI_API_KEY not configured"}

        # 2. Gemini / Nano Banana Pro (in-process via image_gen module)
        from . import image_gen

        gemini_key = image_gen.resolve_api_key()
        sdk_ok = image_gen.sdk_available()
        if gemini_key and sdk_ok:
            channels["gemini_nano_banana"] = {"available": True, "model": image_gen.IMAGE_MODEL}
        else:
            missing = []
            if not gemini_key:
                missing.append("GEMINI_API_KEY/GOOGLE_API_KEY")
            if not sdk_ok:
                missing.append("google-genai SDK")
            channels["gemini_nano_banana"] = {"available": False, "reason": f"missing: {', '.join(missing)}"}
            if "html_prototype" not in fallbacks:
                fallbacks.append("html_prototype")

        # 3. HTML prototype fallback
        try:
            import os as _os
            _html_check_dir = "/tmp/_check_html_fallback"
            _os.makedirs(_html_check_dir, exist_ok=True)
            self._generate_html(
                {"theme": "light", "primary_color": "#6366f1"},
                {"type": "dashboard"},
                ["header", "card", "footer"],
                _html_check_dir,
                "_check",
            )
            channels["html_prototype"] = {"available": True}
        except Exception as e:
            channels["html_prototype"] = {"available": False, "reason": str(e)}

        # 4. Figma MCP (probe env vars)
        figma_token = (os.environ.get("FIGMA_ACCESS_TOKEN") or "").strip()
        channels["figma_mcp"] = {"available": bool(figma_token), "reason": "" if figma_token else "FIGMA_ACCESS_TOKEN not configured"}

        # Fallback priority: html_prototype is always the last resort
        available_channel_names = [k for k, v in channels.items() if v.get("available")]
        if not available_channel_names:
            fallbacks = ["none"]
        elif channels.get("html_prototype", {}).get("available") and "html_prototype" not in fallbacks:
            fallbacks.append("html_prototype")

        has_real_image_gen = (
            channels.get("openai_images", {}).get("available")
            or channels.get("gemini_nano_banana", {}).get("available")
        )
        has_figma = channels.get("figma_mcp", {}).get("available")
        has_html_fallback = channels.get("html_prototype", {}).get("available")

        overall_ok = has_real_image_gen or has_figma or has_html_fallback

        # Degraded mode: only HTML fallback available, no real image generation
        degraded = overall_ok and not has_real_image_gen and not has_figma
        degraded_reason = ""
        if degraded:
            missing = []
            if not channels.get("openai_images", {}).get("available"):
                missing.append("OPENAI_API_KEY")
            if not channels.get("gemini_nano_banana", {}).get("available"):
                missing.append("GEMINI_API_KEY")
            degraded_reason = f"no_image_gen_api: {', '.join(missing)} not configured"

        return {
            "ok": overall_ok,
            "degraded": degraded,
            "degraded_reason": degraded_reason,
            "channels": channels,
            "available": available_channel_names,
            "fallbacks": fallbacks,
        }

    async def check_diagram_resources(self) -> Dict[str, Any]:
        """Check availability of diagram generation resources for architect stage."""
        channels: Dict[str, Any] = {}
        fallbacks: List[str] = []

        # Primary: Gemini / Nano Banana Pro image rendering (in-process)
        from . import image_gen

        gemini_key = image_gen.resolve_api_key()
        sdk_ok = image_gen.sdk_available()
        if gemini_key and sdk_ok:
            channels["gemini_nano_banana"] = {"available": True, "model": image_gen.IMAGE_MODEL}
        else:
            missing = []
            if not gemini_key:
                missing.append("GEMINI_API_KEY/GOOGLE_API_KEY")
            if not sdk_ok:
                missing.append("google-genai SDK")
            channels["gemini_nano_banana"] = {"available": False, "reason": f"missing: {', '.join(missing)}"}

        # Fallback: Mermaid rendering (local CLI or CDN)
        try:
            import subprocess
            result = subprocess.run(["mermaid", "--version"], capture_output=True, text=True, timeout=5)
            mermaid_available = result.returncode == 0
        except Exception:
            mermaid_available = False
        channels["mermaid_cli"] = {"available": mermaid_available}
        if not mermaid_available:
            channels["mermaid_cli"]["reason"] = "mermaid CLI not found (CDN fallback in HTML works)"

        # HTML generation — always available (no external dependency)
        channels["html_renderer"] = {"available": True}

        available = [k for k, v in channels.items() if v.get("available")]
        fallbacks.append("html_renderer")

        # Degraded is driven by offline-render availability (Mermaid CLI). The
        # Gemini image channel is reported above as an enhancement, but a
        # missing image API does not by itself degrade the diagram stage —
        # Mermaid/HTML rendering is always available.
        degraded = not mermaid_available  # CDN-only mode, no offline rendering
        return {
            "ok": True,  # HTML rendering always works (CDN or local)
            "degraded": degraded,
            "degraded_reason": "mermaid_cli_not_installed: CDN fallback requires internet access" if degraded else "",
            "channels": channels,
            "available": available,
            "fallbacks": fallbacks,
        }

    # ── Phase 5: Design Tokens & Screen Plan generation ────────────────

    @staticmethod
    def generate_design_tokens(design_spec: str) -> Dict[str, Any]:
        """Extract structured design tokens from spec (colors, typography, spacing).

        Returns dict with ``degraded: True`` when using defaults — spec had no
        actionable design information.
        """
        spec_lower = design_spec.lower()
        tokens: Dict[str, Any] = {}

        # Primary color
        import re
        colors = re.findall(r"#[0-9a-fA-F]{6}", design_spec)
        tokens["primary"] = colors[0] if colors else "#6366f1"
        tokens["secondary"] = colors[1] if len(colors) > 1 else "#059669"

        # Background / surface
        is_dark = "dark" in spec_lower
        tokens["background"] = "#0f0f1a" if is_dark else "#f8f9fa"
        tokens["surface"] = "#1a1a2e" if is_dark else "#ffffff"
        tokens["text_primary"] = "#e2e8f0" if is_dark else "#1e293b"
        tokens["text_muted"] = "#94a3b8" if is_dark else "#64748b"

        # Typography
        tokens["font_family"] = "Inter, system-ui, -apple-system, sans-serif"
        tokens["font_sizes"] = {
            "h1": "28px", "h2": "22px", "h3": "18px",
            "h4": "16px", "h5": "14px", "h6": "13px",
            "body": "14px", "caption": "12px",
        }
        tokens["spacing_grid"] = "4px"
        tokens["border_radius"] = {"sm": "6px", "md": "10px", "lg": "16px"}

        style_keywords = ("glass", "frost", "neon", "cyber", "minimal", "brutal", "editorial", "swiss")
        has_style = any(kw in spec_lower for kw in style_keywords)
        if "glass" in spec_lower or "frost" in spec_lower:
            tokens["style"] = "glassmorphism"
        elif "neon" in spec_lower or "cyber" in spec_lower:
            tokens["style"] = "dark neon"
        elif "minimal" in spec_lower:
            tokens["style"] = "minimal"

        tokens["degraded"] = not colors and not has_style and not is_dark
        if tokens["degraded"]:
            tokens["degraded_reason"] = "no_colors_or_style_in_spec: using default design tokens"

        return tokens

    @staticmethod
    def generate_screen_plan(design_spec: str) -> Dict[str, Any]:
        """Generate screen plan from design spec — list of screens + state matrix."""
        spec_lower = design_spec.lower()
        screens: List[Dict[str, Any]] = []

        # Extract page/screen titles from markdown headings
        seen_titles: set = set()
        for line in design_spec.splitlines():
            s = line.strip()
            if s.startswith("## ") and len(s) > 3:
                title = s[3:].strip()
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    screens.append({
                        "title": title,
                        "route": f"/{title.lower().replace(' ', '-')}",
                        "states": ["loading", "empty", "error", "success"],
                    })

        if not screens:
            # Fallback: detect pages from common keywords
            page_keywords = ["dashboard", "login", "register", "profile", "settings",
                             "list", "detail", "create", "edit", "home", "landing"]
            for kw in page_keywords:
                if kw in spec_lower:
                    title = kw.capitalize()
                    if title not in seen_titles:
                        seen_titles.add(title)
                        screens.append({
                            "title": title,
                            "route": f"/{kw}",
                            "states": ["loading", "empty", "error", "success"],
                        })

        if not screens:
            screens.append({
                "title": "Main",
                "route": "/",
                "states": ["loading", "empty", "error", "success"],
            })

        has_spec_content = bool(seen_titles)  # headings or keywords matched

        return {
            "screens": screens,
            "state_matrix": {
                "loading": "Skeleton/spinner while data loads",
                "empty": "Empty state with CTA when no data",
                "error": "Error state with retry action",
                "success": "Normal data display with full UI",
            },
            "degraded": not has_spec_content,
            "degraded_reason": (
                "no_headings_or_page_keywords_in_spec: using single Main screen fallback"
            ) if not has_spec_content else "",
        }

    # ── Phase 5: Consistency check ─────────────────────────────────────

    @staticmethod
    def check_architecture_consistency(
        api_contract: Dict[str, Any],
        data_model: Dict[str, Any],
        file_plan: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        """Cross-check api_contract entities ↔ data_model entities ↔ file_plan directories.

        Returns (ok, list of inconsistency messages).
        """
        issues: List[str] = []

        # ── 1. Entity cross-reference (both directions) ──
        api_entities: set = set()
        for endpoint in api_contract.get("endpoints", []):
            name = endpoint.get("entity", endpoint.get("resource", ""))
            if name:
                api_entities.add(name.lower())

        model_entity_names: set = set()
        model_entities: List[Dict[str, Any]] = data_model.get("tables", data_model.get("entities", []))
        for table in model_entities:
            name = table.get("name", table.get("table", ""))
            if name:
                model_entity_names.add(name.lower())

        # 1a: Every API entity must have a matching data model table
        for ae in api_entities:
            ae_clean = ae.rstrip("s")
            ae_plural = ae + "s"
            if (
                ae not in model_entity_names
                and ae_plural not in model_entity_names
                and ae_clean not in model_entity_names
            ):
                issues.append(f"API entity '{ae}' not found in data model")

        # 1b: Every data model table should have a matching API entity
        # (only flag when there are API entities defined — skip if only generic "items" table)
        if api_entities and model_entity_names != {"items"}:
            for mn in model_entity_names:
                mn_singular = mn.rstrip("s")
                mn_plural = mn + "s"
                if (
                    mn not in api_entities
                    and mn_singular not in api_entities
                    and mn_plural not in api_entities
                ):
                    issues.append(f"Data model table '{mn}' has no corresponding API entity")

        # ── 2. Foreign key validation ──
        for table in model_entities:
            table_name = table.get("name", "")
            for field in table.get("fields", []):
                fk = field.get("fk", "")
                if fk:
                    fk_table = fk.split(".")[0] if "." in fk else fk
                    if fk_table.lower() not in model_entity_names:
                        issues.append(
                            f"Foreign key '{field['name']}' in table '{table_name}' "
                            f"references '{fk_table}' which is not in data model"
                        )

        # ── 3. Field type validation ──
        valid_types = {
            "uuid", "varchar", "text", "integer", "int", "bigint", "smallint",
            "boolean", "bool", "timestamp", "date", "time", "datetime",
            "decimal", "numeric", "float", "double", "real",
            "json", "jsonb", "bytea", "blob", "enum",
        }
        for table in model_entities:
            table_name = table.get("name", "")
            for field in table.get("fields", []):
                ftype = field.get("type", "").lower().split("(")[0].split("<")[0].strip()
                if ftype and not any(ftype.startswith(vt) for vt in valid_types):
                    issues.append(
                        f"Unknown field type '{field['type']}' for '{field['name']}' in table '{table_name}'"
                    )

        # ── 4. Route-to-directory mapping ──
        file_routes: set = set()
        for entry in file_plan.get("files", file_plan.get("directories", [])):
            name = entry.get("name", "").lower()
            if name:
                file_routes.add(name)

        api_routes: set = set()
        for endpoint in api_contract.get("endpoints", []):
            path = endpoint.get("path", "").lower()
            for seg in path.strip("/").split("/"):
                if seg and not seg.startswith("{") and not seg.startswith(":"):
                    api_routes.add(seg)

        dir_mismatches = file_routes - api_routes
        if dir_mismatches and len(dir_mismatches) < len(file_routes):
            for dm in dir_mismatches:
                issues.append(f"File plan directory '{dm}' has no corresponding API route segment")

        # ── 5. Degraded artifact aggregation ──
        degraded_sources = []
        if api_contract.get("degraded"):
            degraded_sources.append("api_contract")
        if data_model.get("degraded"):
            degraded_sources.append("data_model")
        if file_plan.get("degraded"):
            degraded_sources.append("file_plan")
        if degraded_sources:
            issues.append(
                f"Architecture consistency based on degraded/generic data: "
                f"{', '.join(degraded_sources)}"
            )

        return (len(issues) == 0, issues)

    # ── Public API ─────────────────────────────────────────────────────

    async def generate_mockup(
        self,
        task_id: str,
        stage_id: str,
        design_spec: str,
        project_name: str = "",
    ) -> Dict[str, Any]:
        """Generate a visual UI mockup from a design specification.

        Returns:
            ``{"ok": True, ...}`` when real image (PNG) generated via image gen API.
            ``{"ok": False, "degraded": True, ...}`` when only HTML fallback produced.
            ``{"ok": False, "degraded": False, ...}`` when nothing could be generated.
        """
        out_dir, rel_prefix = self._visual_out_dir(task_id, MOCKUP_DIR)

        # Extract style and layout from spec (use project_name as fallback for layout detection)
        style, layout, components = self._parse_spec(design_spec, project_name=project_name)

        # 1. Generate mockup image (try Nano Banana Pro / Gemini API)
        image_path = await self._generate_image(
            design_spec, style, out_dir, task_id,
        )

        # 2. Generate interactive HTML prototype (always available as pure-Python fallback)
        html_path = self._generate_html(
            style, layout, components, out_dir, project_name,
        )

        image_ok = bool(image_path)
        html_ok = bool(html_path)

        rel_image = ""
        rel_html = ""
        if image_path:
            rel_image = self._rel_path(rel_prefix, os.path.basename(image_path))
        if html_path:
            rel_html = self._rel_path(rel_prefix, os.path.basename(html_path))

        return {
            "ok": image_ok,
            "degraded": not image_ok and html_ok,
            "imagePath": rel_image,
            "htmlPath": rel_html,
            "imageExists": image_ok,
            "htmlExists": html_ok,
            "prompt": self._build_image_prompt(design_spec, style, layout),
        }

    # ── Image Generation ───────────────────────────────────────────────

    async def _generate_image(
        self,
        spec: str,
        style: Dict[str, Any],
        out_dir: str,
        task_id: str,
    ) -> Optional[str]:
        """Generate UI mockup image via Nano Banana Pro (Gemini 3 Pro Image).

        Uses the in-process ``image_gen`` module (server-safe). Returns the PNG
        path, or ``None`` so the caller falls back to the HTML prototype.
        """
        from . import image_gen

        prompt = self._build_image_prompt(spec, style, {})
        filepath = os.path.join(out_dir, f"ui-mockup-{task_id[:12]}.png")
        return await image_gen.generate_image(
            prompt, filepath, resolution="2K", aspect_ratio="16:9",
        )

    def _build_image_prompt(
        self,
        spec: str,
        style: Dict[str, Any],
        layout: Dict[str, Any],
    ) -> str:
        """Build a detailed image generation prompt from the design spec."""
        theme = style.get("theme", "modern light")
        primary = style.get("primary_color", "#6366f1")
        layout_type = layout.get("type", "dashboard")  # noqa: F841 — used in f-string below

        return (
            f"Create a high-fidelity UI mockup image of a {layout_type} application. "
            f"Style: {theme} theme with primary color {primary}. "
            f"Must be a realistic, pixel-perfect screenshot of a working application, "
            f"not a wireframe. Use modern UI patterns: "
            f"clear typography hierarchy, generous whitespace, "
            f"subtle shadows, rounded corners. "
            f"Show real content in the UI. "
            f"Design details: {spec[:1500]}"
        )

    # ── HTML Prototype Generation ──────────────────────────────────────

    def _parse_spec(self, spec: str, project_name: str = "") -> Tuple[Dict, Dict, List]:
        """Parse design spec to extract style, layout, and components."""
        spec_lower = spec.lower()
        title_lower = project_name.lower()

        # Theme detection
        style: Dict[str, Any] = {
            "theme": "dark" if "dark" in spec_lower else "light",
            "primary_color": self._extract_color(spec, "#6366f1"),
            "secondary_color": self._extract_color(spec.split("#", 2)[-1] if "#" in spec[1:] else "", "#059669"),
            "font": "Inter, system-ui, sans-serif",
        }

        if "minimal" in spec_lower:
            style["theme"] = "minimal light"
        elif "glass" in spec_lower or "frost" in spec_lower:
            style["theme"] = "glassmorphism"
        elif "neon" in spec_lower or "cyber" in spec_lower:
            style["theme"] = "dark neon"

        # Layout detection — prefer project_name (task title) over spec content,
        # because LLM-generated specs often contain boilerplate like "单页应用"
        # that interferes with keyword detection.
        layout: Dict[str, Any] = {
            "type": "dashboard",
        }
        detect_source = title_lower if title_lower else spec_lower
        if "chat" in detect_source or "messenger" in detect_source:
            layout["type"] = "chat-app"
        elif "kanban" in detect_source:
            layout["type"] = "kanban-board"
        elif "blog" in detect_source or "article" in detect_source or "post" in detect_source:
            layout["type"] = "blog-layout"
        elif "landing" in detect_source or "marketing" in detect_source or "homepage" in detect_source or "portfolio" in detect_source:
            layout["type"] = "landing-page"
        elif "ecommerce" in detect_source or "shop" in detect_source or "store" in detect_source:
            layout["type"] = "ecommerce"
        elif "setting" in detect_source or "config" in detect_source or "preference" in detect_source:
            layout["type"] = "settings-page"
        elif "dashboard" in detect_source or "analytics" in detect_source or "report" in detect_source:
            layout["type"] = "dashboard"
        elif "sidebar" in detect_source or "drawer" in detect_source:
            layout["type"] = "sidebar-layout"

        # Component detection
        components = []
        component_keywords = {
            "header": ["header", "navbar", "navigation", "top bar"],
            "hero": ["hero", "banner", "jumbotron"],
            "sidebar": ["sidebar", "side nav", "drawer"],
            "table": ["table", "grid", "data table", "list"],
            "card": ["card", "tile", "panel"],
            "form": ["form", "input", "field", "search"],
            "button": ["button", "cta", "action"],
            "chart": ["chart", "graph", "statistics", "analytics"],
            "footer": ["footer", "bottom bar"],
            "modal": ["modal", "dialog", "popup", "overlay"],
        }
        for comp, keywords in component_keywords.items():
            if any(k in spec_lower for k in keywords):
                components.append(comp)

        if not components:
            components = ["header", "hero", "footer"]

        return style, layout, components

    def _extract_color(self, text: str, default: str) -> str:
        """Extract hex color code from text, or return default."""
        import re
        colors = re.findall(r"#[0-9a-fA-F]{6}", text)
        return colors[0] if colors else default

    def _generate_html(
        self,
        style: Dict[str, Any],
        layout: Dict[str, Any],
        components: List[str],
        out_dir: str,
        project_name: str,
    ) -> str:
        """Generate an interactive HTML prototype reflecting the design spec.

        The output is intentionally self-contained (no external assets, no
        framework) so it works inside a sandboxed iframe without network
        access. Content is derived from the design spec to produce distinct
        HTML prototypes for different tasks — never a hardcoded template.
        """
        theme = style.get("theme", "light")
        primary = style.get("primary_color", "#6366f1")
        secondary = style.get("secondary_color", "#059669")
        is_dark = "dark" in str(theme).lower()
        layout_type = layout.get("type", "dashboard")

        bg = "#0f0f1a" if is_dark else "#f8f9fa"
        surface = "#1a1a2e" if is_dark else "#ffffff"
        text_color = "#e2e8f0" if is_dark else "#1e293b"
        text_muted = "#94a3b8" if is_dark else "#64748b"
        border = "rgba(255,255,255,0.06)" if is_dark else "rgba(0,0,0,0.06)"
        border_strong = "rgba(255,255,255,0.15)" if is_dark else "rgba(0,0,0,0.15)"
        input_bg = "rgba(255,255,255,0.05)" if is_dark else "rgba(0,0,0,0.02)"

        # ── Pick layout template from HtmlLayouts ──────────────────────
        from ._html_layouts import HtmlLayouts

        layout_fn_name = f"_layout_{layout_type.replace('-', '_')}"
        layout_fn = getattr(HtmlLayouts, layout_fn_name, None)
        if layout_fn is not None:
            main_content = layout_fn(
                primary, secondary, surface, text_color, text_muted,
                border, border_strong, input_bg, is_dark, project_name,
            )
        else:
            main_content = HtmlLayouts._layout_dashboard(
                primary, secondary, surface, text_color, text_muted,
                border, border_strong, input_bg, is_dark, project_name,
            )

        # ── Layout-specific CSS overrides ───────────────────────────────
        # Each layout type gets its own visual identity — different grid
        # layout, card styles, colour accents, and spacing — so the HTML
        # prototypes look genuinely different, not just different content in
        # the same CSS skeleton.
        css_overrides = {
            "dashboard": """
.sidebar { border-right: 2px solid {primary}30; }
.stat-card { border-left: 3px solid {primary}; border-radius: 10px; }
.card { border-left: 3px solid {primary}40; border-radius: 10px; }
""",
            "landing-page": """
.content { grid-template-columns: 1fr !important; }
.main { padding: 0 !important; border-radius: 0; }
.navbar { background: {primary}08; }
.nav-links { margin-left: auto; }
""",
            "kanban-board": """
.content { grid-template-columns: 1fr !important; }
.sidebar { display: none !important; }
.main { padding: 16px !important; }
.navbar { border-bottom: 2px solid {secondary}; }
""",
            "chat-app": """
.content { grid-template-columns: 300px 1fr !important; }
.sidebar { border-right: 1px solid {border}; background: {input_bg}; }
.main { padding: 0 !important; display: flex; flex-direction: column; }
.navbar { border-bottom: 1px solid {primary}30; }
""",
            "ecommerce": """
.content { grid-template-columns: 220px 1fr !important; }
.sidebar { background: {surface}; }
.stat-card .value { color: {secondary}; }
.card { text-align: center; padding: 24px; }
""",
            "blog-layout": """
.content { grid-template-columns: 1fr 300px !important; }
.main { padding: 32px 48px !important; }
.sidebar { order: 2; border-right: none; border-left: 1px solid {border}; }
.card { border-radius: 12px; overflow: hidden; }
.card h3 { font-size: 17px; }
""",
            "settings-page": """
.content { grid-template-columns: 240px 1fr !important; }
.sidebar { background: {input_bg}; }
.main { max-width: 640px; padding: 32px !important; }
.form-row { max-width: 100%; }
""",
            "sidebar-layout": """
.content { grid-template-columns: 200px 1fr !important; }
.sidebar { background: {surface}; border-right: 2px solid {primary}20; }
.main { padding: 24px 32px !important; }
""",
        }
        extra_css = css_overrides.get(layout_type, "")
        # Inject colour variables into overrides. Use replace() (not .format())
        # because the CSS contains literal braces and ``prop: value`` colons that
        # str.format misinterprets as field names / format specs.
        if extra_css:
            for _token, _value in (
                ("{primary}", primary), ("{secondary}", secondary),
                ("{surface}", surface), ("{border}", border),
                ("{text_color}", text_color), ("{text_muted}", text_muted),
                ("{border_strong}", border_strong), ("{input_bg}", input_bg),
            ):
                extra_css = extra_css.replace(_token, _value)
        extra_css_block = f"\n{extra_css}\n" if extra_css else ""

        # ── Build the page ────────────────────────────────────────────
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{project_name or 'UI Mockup'} — Agent Hub 设计稿</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Inter', system-ui, -apple-system, sans-serif; background: {bg}; color: {text_color}; line-height: 1.6; }}
.container {{ max-width: 1280px; margin: 0 auto; padding: 24px; }}
.mockup-frame {{ background: {surface}; border-radius: 16px; border: 1px solid {border}; overflow: hidden; min-height: 600px; }}
.toolbar {{ display: flex; align-items: center; gap: 12px; padding: 16px 24px; border-bottom: 1px solid {border}; }}
.toolbar-dot {{ width: 12px; height: 12px; border-radius: 50%; }}
.toolbar-dot:nth-child(1) {{ background: #ef4444; }}
.toolbar-dot:nth-child(2) {{ background: #f59e0b; }}
.toolbar-dot:nth-child(3) {{ background: #22c55e; }}
.toolbar-title {{ font-size: 13px; color: {text_muted}; margin-left: 8px; }}
.navbar {{ display: flex; align-items: center; justify-content: space-between; padding: 12px 24px; background: {surface}; border-bottom: 1px solid {border}; }}
.logo {{ font-weight: 700; font-size: 18px; color: {primary}; }}
.nav-links {{ display: flex; gap: 24px; }}
.nav-links a {{ color: {text_muted}; text-decoration: none; font-size: 14px; padding: 4px 2px; border-bottom: 2px solid transparent; transition: all 0.2s; cursor: pointer; }}
.nav-links a:hover {{ color: {text_color}; }}
.nav-links a.active {{ color: {primary}; border-bottom-color: {primary}; font-weight: 600; }}
.content {{ display: grid; grid-template-columns: 240px 1fr; min-height: 600px; }}
.sidebar {{ padding: 24px 16px; border-right: 1px solid {border}; }}
.sidebar-item {{ padding: 10px 16px; border-radius: 8px; margin-bottom: 4px; font-size: 14px; color: {text_muted}; cursor: pointer; transition: all 0.2s; user-select: none; }}
.sidebar-item:hover {{ background: {primary}15; color: {primary}; }}
.sidebar-item.active {{ background: {primary}; color: #fff; }}
.main {{ padding: 24px; }}
.main-full {{ padding: 24px; }}
.view {{ display: none; animation: fadeIn 0.18s ease; }}
.view.active {{ display: block; }}
@keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(4px); }} to {{ opacity: 1; transform: none; }} }}
.header-row {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }}
.header-row h1 {{ font-size: 24px; font-weight: 600; }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
.stat-card {{ padding: 20px; border-radius: 12px; background: {surface}; border: 1px solid {border}; }}
.stat-card .label {{ font-size: 12px; color: {text_muted}; text-transform: uppercase; letter-spacing: 0.5px; }}
.stat-card .value {{ font-size: 28px; font-weight: 700; margin-top: 8px; color: {primary}; }}
.card-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }}
.card {{ padding: 20px; border-radius: 12px; background: {surface}; border: 1px solid {border}; transition: transform 0.2s; }}
.card:hover {{ transform: translateY(-2px); }}
.card h3 {{ font-size: 15px; margin-bottom: 8px; }}
.card p {{ font-size: 13px; color: {text_muted}; margin-bottom: 12px; }}
.badge {{ display: inline-block; padding: 2px 10px; border-radius: 100px; font-size: 12px; background: {primary}15; color: {primary}; }}
.badge-warn {{ background: rgba(245, 158, 11, 0.15); color: #f59e0b; }}
.badge-ok {{ background: rgba(34, 197, 94, 0.15); color: #22c55e; }}
.btn {{ display: inline-flex; align-items: center; gap: 6px; padding: 8px 20px; border-radius: 8px; font-size: 14px; font-weight: 500; cursor: pointer; border: none; transition: all 0.2s; font-family: inherit; }}
.btn-primary {{ background: {primary}; color: #fff; }}
.btn-primary:hover {{ opacity: 0.9; }}
.btn-outline {{ border: 1px solid {border_strong}; background: transparent; color: {text_color}; }}
.btn-outline:hover {{ background: {input_bg}; }}
.list-table {{ width: 100%; border-collapse: collapse; background: {surface}; border-radius: 12px; overflow: hidden; border: 1px solid {border}; }}
.list-table th, .list-table td {{ text-align: left; padding: 12px 16px; border-bottom: 1px solid {border}; font-size: 14px; }}
.list-table tr:last-child td {{ border-bottom: none; }}
.list-table th {{ font-size: 11px; color: {text_muted}; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; background: {input_bg}; }}
.progress {{ width: 100%; height: 6px; background: {primary}25; border-radius: 3px; overflow: hidden; }}
.progress > span {{ display: block; height: 100%; background: {primary}; border-radius: 3px; }}
.chart-placeholder {{ height: 220px; border-radius: 12px; background: linear-gradient(135deg, {primary}15, {primary}30); display: flex; align-items: center; justify-content: center; color: {text_muted}; font-size: 13px; margin-bottom: 24px; border: 1px solid {border}; }}
.form-row {{ display: flex; align-items: center; gap: 16px; padding: 14px 0; border-bottom: 1px solid {border}; }}
.form-row:last-child {{ border-bottom: none; }}
.form-row label {{ flex: 0 0 220px; font-size: 14px; color: {text_color}; }}
.form-row input, .form-row select {{ flex: 1; padding: 8px 12px; border-radius: 6px; border: 1px solid {border_strong}; background: {input_bg}; color: {text_color}; font-size: 14px; font-family: inherit; }}
.form-row .hint {{ font-size: 12px; color: {text_muted}; margin-top: 4px; }}
.team-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; }}
.team-card {{ padding: 20px; border-radius: 12px; background: {surface}; border: 1px solid {border}; text-align: center; }}
.avatar {{ width: 48px; height: 48px; border-radius: 50%; background: {primary}; color: #fff; display: inline-flex; align-items: center; justify-content: center; font-weight: 600; font-size: 16px; margin-bottom: 12px; }}
.team-card h4 {{ font-size: 14px; margin-bottom: 2px; }}
.team-card p {{ font-size: 12px; color: {text_muted}; }}
.footer {{ text-align: center; padding: 24px; color: {text_muted}; font-size: 13px; border-top: 1px solid {border}; }}
@media (max-width: 768px) {{ .content {{ grid-template-columns: 1fr; }} .sidebar {{ display: none; }} .nav-links {{ gap: 12px; }} }}
{extra_css_block}</style></head>
<body>
<div class="container">
  <div class="mockup-frame">
    <div class="toolbar">
      <span class="toolbar-dot"></span><span class="toolbar-dot"></span><span class="toolbar-dot"></span>
      <span class="toolbar-title">{project_name or 'UI Mockup'}</span>
    </div>
    <nav class="navbar">
      <div class="logo">{project_name[:10] if project_name else 'Hub'}</div>
      <div class="nav-links">
        <a data-view="main" class="active">Overview</a>
        <a data-view="list">Details</a>
        <a data-view="detail">Activity</a>
        <a data-view="settings">Settings</a>
      </div>
    </nav>
      <aside class="sidebar">
        <div class="sidebar-item active" data-view="main">{'🏠 Overview' if layout_type in ('landing-page','blog-layout') else '📊 Dashboard'}</div>
        <div class="sidebar-item" data-view="list">📋 Data</div>
        <div class="sidebar-item" data-view="detail">🔍 Detail</div>
        <div class="sidebar-item" data-view="settings">⚙️ Settings</div>
      </aside>
      <main class="main">
        {main_content}
      </main>
    <div class="footer">Agent Hub · AI 生成的 UI 设计稿 · {datetime.utcnow().strftime('%Y-%m-%d')}</div>
  </div>
</div>
<script>
(function () {{
  const triggers = document.querySelectorAll('[data-view]');
  const views = document.querySelectorAll('section.view');

  function show(target) {{
    if (!target) return;
    views.forEach(function (s) {{
      s.classList.toggle('active', s.dataset.view === target);
    }});
    triggers.forEach(function (el) {{
      if (el.tagName === 'SECTION') return;
      el.classList.toggle('active', el.dataset.view === target);
    }});
  }}

  triggers.forEach(function (el) {{
    if (el.tagName === 'SECTION') return;
    el.addEventListener('click', function (e) {{
      e.preventDefault();
      show(el.dataset.view);
    }});
  }});
}})();
</script>
</body>
</html>"""

        filename = f"ui-prototype-{_slugify_filename(project_name or 'mockup')}.html"
        os.makedirs(out_dir, exist_ok=True)
        filepath = os.path.join(out_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("[ui-visualizer] HTML prototype: %s", filepath)
        return filepath

    # ═════════════════════════════════════════════════════════════════
    #  Architecture Diagram Generation
    # ═════════════════════════════════════════════════════════════════

    async def generate_architecture_diagram(
        self,
        task_id: str,
        stage_id: str,
        arch_spec: str,
        project_name: str = "",
    ) -> Dict[str, Any]:
        """Generate architecture diagrams from an architecture specification.

        Returns dict with ``degraded: True`` when no real components detected
        in spec (only default 3-tier template used).
        """
        out_dir, rel_prefix = self._visual_out_dir(task_id, ARCH_DIR)

        # Parse spec to extract components and flows
        components, flows, arch_degraded, arch_degraded_reason = self._parse_architecture_spec(arch_spec)

        # 1. Primary: architecture diagram as a rendered image (Nano Banana Pro)
        image_path = await self._generate_arch_image(
            arch_spec, components, flows, out_dir, task_id, project_name,
        )

        # 2. Companion / fallback: Mermaid markdown + HTML rendering
        diagrams = self._generate_mermaid_diagrams(arch_spec, components, flows)
        html_path = self._generate_arch_html(
            diagrams, components, out_dir, project_name or "System Architecture",
        )

        rel_html = self._rel_path(rel_prefix, os.path.basename(html_path)) if html_path else ""
        rel_image = self._rel_path(rel_prefix, os.path.basename(image_path)) if image_path else ""

        return {
            "ok": True,
            "imagePath": rel_image,
            "imageExists": bool(image_path),
            "htmlPath": rel_html,
            "mermaidRaw": diagrams,
            "componentCount": len(components),
            "flowCount": len(flows),
            "degraded": arch_degraded,
            "degraded_reason": arch_degraded_reason,
        }

    async def _generate_arch_image(
        self,
        spec: str,
        components: List[Dict[str, str]],
        flows: List[Dict[str, str]],
        out_dir: str,
        task_id: str,
        project_name: str = "",
    ) -> Optional[str]:
        """Render an architecture diagram as an image via Nano Banana Pro.

        Returns the PNG path, or ``None`` so the caller falls back to the
        Mermaid HTML rendering.
        """
        from . import image_gen

        prompt = self._build_arch_image_prompt(spec, components, flows, project_name)
        filepath = os.path.join(out_dir, f"architecture-{task_id[:12]}.png")
        return await image_gen.generate_image(
            prompt, filepath, resolution="2K", aspect_ratio="16:9",
        )

    def _build_arch_image_prompt(
        self,
        spec: str,
        components: List[Dict[str, str]],
        flows: List[Dict[str, str]],
        project_name: str = "",
    ) -> str:
        """Build an image prompt for a clean, professional architecture diagram."""
        comp_names = ", ".join(c["name"] for c in components) or "Frontend, Backend API, Database"
        flow_desc = "; ".join(
            f"{f['source']} → {f['target']} ({f['label']})" for f in flows[:12]
        ) or "Frontend → Backend API → Database"
        title = project_name or "System Architecture"
        return (
            f"Create a clean, professional software architecture diagram titled '{title}'. "
            f"Flat modern infographic style on a light background, clear boxes with labels, "
            f"directional arrows, grouped layers (client / server / data / external). "
            f"Use a coherent color palette (indigo, emerald, amber, slate), legible sans-serif "
            f"labels, generous spacing, subtle shadows. Not hand-drawn, not a screenshot. "
            f"Components: {comp_names}. "
            f"Connections: {flow_desc}. "
            f"Design context: {spec[:1200]}"
        )

    # ── Architecture Spec Parsing ─────────────────────────────────────

    def _parse_architecture_spec(
        self,
        spec: str,
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], bool, str]:
        """Parse architecture spec to extract system components and data flows.

        Returns (components, flows, degraded, degraded_reason).
        """
        spec_lower = spec.lower()

        # Detect common components from spec keywords
        component_keywords: Dict[str, str] = {
            "Frontend": "frontend|vue|react|angular|svelte|next\\.?js|nuxt|ui layer|client",
            "Backend API": "backend|api|fastapi|flask|django|express|spring|go server|rest|graphql",
            "Database": "database|db|postgres|mysql|sqlite|mongodb|redis|supabase|sqlalchemy",
            "Cache": "cache|redis|memcached|varnish|cdn",
            "Message Queue": "queue|kafka|rabbitmq|nats|pub/sub|message broker",
            "Auth Service": "auth|oauth|jwt|sso|keycloak|auth0",
            "File Storage": "storage|s3|oss|minio|blob|file upload",
            "Search Service": "search|elasticsearch|meilisearch|algolia|solr",
            "AI/ML Service": "ai|ml|llm|openai|model|inference|embedding|vector",
            "WebSocket": "websocket|socket|ws|real.?time|ws",
            "Load Balancer": "load balancer|nginx|gateway|proxy|reverse proxy",
            "CI/CD": "ci|cd|jenkins|github action|gitlab ci|deploy",
            "Monitoring": "monitor|prometheus|grafana|datadog|sentry|logging|observability",
            "External Service": "external|third.?party|saas|webhook|integration",
        }

        components: List[Dict[str, str]] = []
        found_component_types: set = set()
        for component_name, pattern in component_keywords.items():
            if re.search(pattern, spec_lower):
                if component_name not in found_component_types:
                    lines = spec.split("\n")
                    description = ""
                    for line in lines:
                        if re.search(pattern, line.lower()):
                            description = line.strip()[:120]
                            break
                    components.append({
                        "name": component_name,
                        "description": description or f"{component_name} layer",
                    })
                    found_component_types.add(component_name)

        degraded = False
        degraded_reason = ""
        if not components:
            degraded = True
            degraded_reason = "no_component_keywords_in_spec: using default 3-tier web stack"
            components = [
                {"name": "Frontend", "description": "Client-side UI layer (Vue/React)"},
                {"name": "Backend API", "description": "Server-side API service"},
                {"name": "Database", "description": "Primary data store"},
            ]

        # Detect data flows between components
        flows: List[Dict[str, str]] = []
        flow_patterns = [
            ("Frontend", "Backend API", "HTTP/API requests"),
            ("Backend API", "Database", "CRUD queries"),
            ("Backend API", "Cache", "Cache read/write"),
            ("Backend API", "Message Queue", "Async message dispatch"),
            ("Backend API", "Auth Service", "Auth token validation"),
            ("Backend API", "Search Service", "Search queries"),
            ("Backend API", "AI/ML Service", "Model inference requests"),
            ("Frontend", "WebSocket", "Real-time updates"),
            ("Load Balancer", "Frontend", "Traffic routing"),
            ("Backend API", "File Storage", "File upload/download"),
            ("Backend API", "External Service", "Third-party API calls"),
            ("CI/CD", "Backend API", "Auto-deploy"),
            ("Monitoring", "Backend API", "Telemetry data collection"),
        ]

        component_names = {c["name"] for c in components}
        for src, dst, label in flow_patterns:
            if src in component_names and dst in component_names:
                flows.append({"source": src, "target": dst, "label": label})

        return components, flows, degraded, degraded_reason

    # ── Mermaid Markdown Generation ───────────────────────────────────

    def _generate_mermaid_diagrams(
        self,
        spec: str,
        components: List[Dict[str, str]],
        flows: List[Dict[str, str]],
    ) -> Dict[str, str]:
        """Generate Mermaid diagram markdown for multiple views."""

        # 1. System Architecture Overview (flowchart TD)
        arch_lines = ["flowchart TD"]
        # Subgraph for each layer
        frontend_components = [c for c in components
                               if c["name"] in ("Frontend", "WebSocket", "Load Balancer")]
        backend_components = [c for c in components
                              if c["name"] in ("Backend API", "Auth Service", "Cache",
                                               "Message Queue", "Search Service", "AI/ML Service")]
        data_components = [c for c in components
                           if c["name"] in ("Database", "File Storage")]
        external_components = [c for c in components
                               if c["name"] in ("External Service",
                                                "CI/CD", "Monitoring")]

        # Node definitions
        node_map: Dict[str, str] = {}
        node_id = 0
        def _node(name: str, style_str: str = "") -> str:
            nonlocal node_id
            nid = f"N{node_id}"
            node_map[name] = nid
            node_id += 1
            san = name.replace(" ", "_").replace("/", "_")
            return f"    {nid}[{san}]{style_str}"

        # Define nodes per layer
        for comp in frontend_components:
            arch_lines.append(_node(comp["name"], ":::frontend"))
        for comp in backend_components:
            arch_lines.append(_node(comp["name"], ":::backend"))
        for comp in data_components:
            arch_lines.append(_node(comp["name"], ":::data"))
        for comp in external_components:
            arch_lines.append(_node(comp["name"], ":::external"))

        # Edges
        for flow in flows:
            src_id = node_map.get(flow["source"])
            tgt_id = node_map.get(flow["target"])
            if src_id and tgt_id:
                arch_lines.append(f"    {src_id} -->|{flow['label']}| {tgt_id}")

        # Styling
        arch_lines.extend([
            "",
            "    classDef frontend fill:#6366f1,color:#fff,stroke:#4338ca",
            "    classDef backend fill:#059669,color:#fff,stroke:#047857",
            "    classDef data fill:#d97706,color:#fff,stroke:#b45309",
            "    classDef external fill:#6b7280,color:#fff,stroke:#4b5563",
        ])
        arch_diagram = "\n".join(arch_lines)

        # 2. Data Flow / Sequence Diagram
        seq_lines = ["sequenceDiagram"]
        # Detect key interaction flows from spec
        has_auth = any(c["name"] == "Auth Service" for c in components)
        has_db = any(c["name"] == "Database" for c in components)
        has_cache = any(c["name"] == "Cache" for c in components)
        has_queue = any(c["name"] == "Message Queue" for c in components)
        has_ai = any(c["name"] == "AI/ML Service" for c in components)

        seq_lines.append("    participant F as Frontend")
        seq_lines.append("    participant B as Backend API")
        if has_auth:
            seq_lines.append("    participant A as Auth Service")
        if has_cache:
            seq_lines.append("    participant C as Cache")
        if has_db:
            seq_lines.append("    participant D as Database")
        if has_queue:
            seq_lines.append("    participant Q as Message Queue")
        if has_ai:
            seq_lines.append("    participant AI as AI/ML Service")

        seq_lines.append("")
        seq_lines.append("    F->>+B: HTTP Request (API call)")
        if has_auth:
            seq_lines.append("    B->>+A: Validate Token")
            seq_lines.append("    A-->>-B: Token Valid")
        if has_cache:
            seq_lines.append("    B->>+C: Check Cache")
            seq_lines.append("    C-->>-B: Cache Miss")
        if has_db:
            seq_lines.append("    B->>+D: Query Data")
            seq_lines.append("    D-->>-B: Return Results")
        if has_ai:
            seq_lines.append("    B->>+AI: Inference Request")
            seq_lines.append("    AI-->>-B: Prediction Result")
        if has_queue:
            seq_lines.append("    B->>+Q: Dispatch Event")
            seq_lines.append("    Q-->>-B: Ack")
        seq_lines.append("    B-->>-F: HTTP Response (JSON)")
        seq_diagram = "\n".join(seq_lines)

        # 3. Deployment / Component Layer diagram
        deploy_lines = ["flowchart LR"]
        deploy_lines.append("    subgraph Client[Client Layer]")
        for comp in frontend_components:
            deploy_lines.append(f"        {comp['name'].replace(' ', '_')}[{comp['name']}]")
        deploy_lines.append("    end")
        deploy_lines.append("    subgraph Server[Server Layer]")
        for comp in backend_components:
            deploy_lines.append(f"        {comp['name'].replace(' ', '_')}[{comp['name']}]")
        deploy_lines.append("    end")
        deploy_lines.append("    subgraph Data[Data Layer]")
        for comp in data_components:
            deploy_lines.append(f"        {comp['name'].replace(' ', '_')}[{comp['name']}]")
        deploy_lines.append("    end")
        if external_components:
            deploy_lines.append("    subgraph External[External / DevOps]")
            for comp in external_components:
                deploy_lines.append(f"        {comp['name'].replace(' ', '_')}[{comp['name']}]")
            deploy_lines.append("    end")

        # Edges between layers
        if frontend_components and backend_components:
            deploy_lines.append("    Client -->|API Calls| Server")
        if backend_components and data_components:
            deploy_lines.append("    Server -->|Data Access| Data")
        if external_components:
            deploy_lines.append("    Server -.->|Integrates| External")

        deploy_diagram = "\n".join(deploy_lines)

        return {
            "architecture": arch_diagram,
            "sequence": seq_diagram,
            "deployment": deploy_diagram,
        }

    # ── Architecture HTML Generation ──────────────────────────────────

    def _render_mermaid_svg(self, mermaid_code: str, diagram_name: str) -> str:
        """Try to pre-render Mermaid to SVG via local CLI. Returns SVG string or empty."""
        try:
            import subprocess
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False, encoding="utf-8") as tf:
                tf.write(mermaid_code)
                mmd_path = tf.name
            try:
                result = subprocess.run(
                    ["mmdc", "-i", mmd_path, "-o", "-", "-b", "transparent"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0 and result.stdout.strip().startswith("<svg"):
                    return result.stdout.strip()
            finally:
                os.unlink(mmd_path)
        except Exception:
            pass
        return ""

    def _generate_arch_html(
        self,
        diagrams: Dict[str, str],
        components: List[Dict[str, str]],
        out_dir: str,
        project_name: str,
    ) -> str:
        """Wrap Mermaid diagrams in a standalone HTML page.

        Pre-renders SVGs via local mermaid-cli when available (offline-safe).
        Falls back to CDN-loaded Mermaid.js with noscript plain-text backup.
        """
        import json

        mermaid_config = {
            "theme": "dark",
            "themeVariables": {
                "primaryColor": "#6366f1",
                "primaryTextColor": "#ffffff",
                "primaryBorderColor": "#4338ca",
                "lineColor": "#94a3b8",
                "secondaryColor": "#059669",
                "tertiaryColor": "#d97706",
                "fontSize": "14px",
            },
        }

        # Pre-render SVGs via local CLI when available
        pre_rendered: Dict[str, str] = {}
        for key in ("architecture", "sequence", "deployment"):
            svg = self._render_mermaid_svg(diagrams.get(key, ""), key)
            if svg:
                pre_rendered[key] = svg
        use_cdn = not pre_rendered  # need CDN fallback if no local CLI

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{project_name} — 架构图</title>
"""
        if use_cdn:
            html += '<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>\n'
        html += """<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    background: #0f0f1a;
    color: #e2e8f0;
    line-height: 1.6;
}
.header {
    padding: 24px 32px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    display: flex;
    align-items: center;
    gap: 12px;
}
.header h1 { font-size: 20px; font-weight: 600; }
.header .subtitle { color: #94a3b8; font-size: 13px; }
.diagram-section {
    padding: 24px 32px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
}
.diagram-section:last-child { border-bottom: none; }
.section-title {
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.section-title .tag {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 100px;
    background: rgba(99,102,241,0.15);
    color: #818cf8;
    font-weight: 500;
}
.mermaid-container {
    background: #1a1a2e;
    border-radius: 12px;
    border: 1px solid rgba(255,255,255,0.08);
    padding: 24px;
    overflow-x: auto;
    min-height: 200px;
    display: flex;
    justify-content: center;
}
.mermaid-container svg { max-width: 100%; height: auto; }
.mermaid-container pre { color: #94a3b8; font-size: 13px; white-space: pre-wrap; }
.component-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 12px;
    margin: 16px 0;
}
.component-card {
    padding: 14px 16px;
    border-radius: 10px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
}
.component-card .name { font-weight: 500; font-size: 14px; }
.component-card .desc { font-size: 12px; color: #94a3b8; margin-top: 4px; }
.footer {
    text-align: center;
    padding: 20px;
    color: #4b5563;
    font-size: 12px;
}
@media (max-width: 768px) {
    .diagram-section { padding: 16px; }
    .header { padding: 16px; flex-direction: column; align-items: flex-start; }
}
</style>
</head>
<body>
<div class="header">
    <h1>{project_name}</h1>
    <span class="subtitle">系统架构图 · AI 自动生成</span>
</div>
"""

        diagram_labels = [
            ("architecture", "📐 系统架构总览", "Architecture Overview"),
            ("sequence", "🔄 核心交互流程", "Sequence Diagram"),
            ("deployment", "🏗️ 分层部署视图", "Deployment View"),
        ]
        for key, title, tag in diagram_labels:
            mermaid_code = diagrams.get(key, "")
            svg = pre_rendered.get(key, "")
            html += f"""<div class="diagram-section">
    <div class="section-title">
        {title} <span class="tag">{tag}</span>
    </div>
    <div class="mermaid-container">
"""
            if svg:
                # Pre-rendered SVG (offline-safe, no JS required)
                html += svg
            else:
                # CDN fallback with noscript backup
                html += f"""        <pre class="mermaid">
{mermaid_code}
        </pre>
        <noscript>
            <pre>{mermaid_code}</pre>
        </noscript>"""
            html += """
    </div>
</div>
"""

        html += f"""<div class="diagram-section">
    <div class="section-title">
        📋 系统组件清单 <span class="tag">{len(components)} components</span>
    </div>
    <div class="component-grid">
"""
        for comp in components:
            html += f"""
        <div class="component-card">
            <div class="name">{comp['name']}</div>
            <div class="desc">{comp['description'][:80]}</div>
        </div>"""

        html += """
    </div>
</div>
<div class="footer">
    Agent Hub · AI 自动生成的架构设计图 · """ + datetime.utcnow().strftime('%Y-%m-%d') + """
</div>
"""
        if use_cdn:
            html += "<script>\nmermaid.initialize(" + json.dumps(mermaid_config) + ");\n</script>\n"
        html += "</body>\n</html>"

        filename = f"architecture-{_slugify_filename(project_name or 'diagram')}.html"
        filepath = os.path.join(out_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("[ui-visualizer] Architecture diagram: %s (pre-rendered=%s)", filepath, bool(pre_rendered))
        return filepath

    # ── Phase 5: Structured Architecture Data Generation ────────────────

    @staticmethod
    def generate_api_contract(spec: str) -> Dict[str, Any]:
        """Extract API contract from architecture spec."""
        endpoints: List[Dict[str, Any]] = []
        spec_lower = spec.lower()

        entities = []
        entity_keywords = ["user", "project", "task", "order", "product", "account",
                          "customer", "invoice", "payment", "subscription", "article",
                          "comment", "message", "notification", "setting", "file",
                          "document", "template", "report", "analytics", "log"]
        for ent in entity_keywords:
            if ent in spec_lower:
                entities.append(ent)

        degraded = False
        if not entities:
            entities = ["item"]
            degraded = True

        for entity in entities:
            base = f"/api/{entity}s"
            endpoints.append({"method": "GET", "path": base, "description": f"List {entity}s", "entity": entity})
            endpoints.append({"method": "POST", "path": base, "description": f"Create {entity}", "entity": entity})
            endpoints.append({"method": "GET", "path": f"{base}/{{id}}", "description": f"Get {entity} by ID", "entity": entity})
            endpoints.append({"method": "PUT", "path": f"{base}/{{id}}", "description": f"Update {entity}", "entity": entity})
            endpoints.append({"method": "DELETE", "path": f"{base}/{{id}}", "description": f"Delete {entity}", "entity": entity})

        if "auth" in spec_lower or "login" in spec_lower:
            endpoints.insert(0, {"method": "POST", "path": "/api/auth/login", "description": "User login", "entity": "auth"})
            endpoints.insert(1, {"method": "POST", "path": "/api/auth/register", "description": "User registration", "entity": "auth"})

        result: Dict[str, Any] = {"endpoints": endpoints, "degraded": degraded}
        if degraded:
            result["degraded_reason"] = "no_entity_keywords_in_spec: using generic item CRUD endpoints"
        return result

    @staticmethod
    def generate_data_model(spec: str) -> Dict[str, Any]:
        """Extract data model from architecture spec."""
        spec_lower = spec.lower()
        tables: List[Dict[str, Any]] = []

        entity_detections = {
            "user": {"name": "users", "description": "User accounts and profiles",
                     "fields": [
                         {"name": "id", "type": "uuid", "pk": True},
                         {"name": "email", "type": "varchar(255)", "unique": True},
                         {"name": "name", "type": "varchar(100)"},
                         {"name": "created_at", "type": "timestamp"},
                     ]},
            "project": {"name": "projects", "description": "Project definitions",
                        "fields": [
                            {"name": "id", "type": "uuid", "pk": True},
                            {"name": "name", "type": "varchar(200)"},
                            {"name": "owner_id", "type": "uuid", "fk": "users.id"},
                            {"name": "status", "type": "varchar(20)"},
                            {"name": "created_at", "type": "timestamp"},
                        ]},
            "task": {"name": "tasks", "description": "Individual work items",
                     "fields": [
                         {"name": "id", "type": "uuid", "pk": True},
                         {"name": "title", "type": "varchar(200)"},
                         {"name": "description", "type": "text"},
                         {"name": "status", "type": "varchar(20)"},
                         {"name": "assignee_id", "type": "uuid", "fk": "users.id"},
                         {"name": "project_id", "type": "uuid", "fk": "projects.id"},
                         {"name": "created_at", "type": "timestamp"},
                     ]},
            "order": {"name": "orders", "description": "Customer orders",
                      "fields": [
                          {"name": "id", "type": "uuid", "pk": True},
                          {"name": "customer_id", "type": "uuid", "fk": "customers.id"},
                          {"name": "total", "type": "decimal(10,2)"},
                          {"name": "status", "type": "varchar(20)"},
                          {"name": "created_at", "type": "timestamp"},
                      ]},
            "product": {"name": "products", "description": "Product catalog",
                        "fields": [
                            {"name": "id", "type": "uuid", "pk": True},
                            {"name": "name", "type": "varchar(200)"},
                            {"name": "price", "type": "decimal(10,2)"},
                            {"name": "description", "type": "text"},
                            {"name": "created_at", "type": "timestamp"},
                        ]},
        }

        for key, table_def in entity_detections.items():
            if key in spec_lower or key + "s" in spec_lower:
                tables.append(table_def)

        degraded = False
        if not tables:
            degraded = True
            tables.append({
                "name": "items",
                "description": "Generic items",
                "fields": [
                    {"name": "id", "type": "uuid", "pk": True},
                    {"name": "name", "type": "varchar(200)"},
                    {"name": "created_at", "type": "timestamp"},
                ],
            })

        result: Dict[str, Any] = {"tables": tables, "degraded": degraded}
        if degraded:
            result["degraded_reason"] = "no_entity_keywords_in_spec: using generic items table"
        return result

    @staticmethod
    def generate_file_plan(spec: str) -> Dict[str, Any]:
        """Extract file/directory plan from architecture spec."""
        spec_lower = spec.lower()
        directories: List[Dict[str, Any]] = []

        if "frontend" in spec_lower or "vue" in spec_lower or "react" in spec_lower:
            directories.append({"name": "frontend", "description": "Frontend application code"})
            directories.append({"name": "frontend/src/components", "description": "Reusable UI components"})
            directories.append({"name": "frontend/src/views", "description": "Page-level views"})
            directories.append({"name": "frontend/src/api", "description": "API client modules"})

        if "backend" in spec_lower or "api" in spec_lower:
            directories.append({"name": "backend", "description": "Backend API service"})
            directories.append({"name": "backend/app/api", "description": "API route definitions"})
            directories.append({"name": "backend/app/models", "description": "Data/ORM models"})
            directories.append({"name": "backend/app/services", "description": "Business logic"})

        if "database" in spec_lower or "db" in spec_lower:
            directories.append({"name": "backend/migrations", "description": "Database migrations"})

        if "test" in spec_lower or "qa" in spec_lower:
            directories.append({"name": "tests", "description": "Test suite"})

        if "deploy" in spec_lower or "docker" in spec_lower:
            directories.append({"name": "docker", "description": "Docker configuration"})

        if "doc" in spec_lower or "docs" in spec_lower:
            directories.append({"name": "docs", "description": "Documentation"})

        degraded = False
        if not directories:
            degraded = True
            directories.append({"name": "src", "description": "Source code"})

        result: Dict[str, Any] = {
            "directories": directories,
            "files": [{"name": d["name"]} for d in directories],
            "degraded": degraded,
        }
        if degraded:
            result["degraded_reason"] = "no_tech_keywords_in_spec: using generic src directory"
        return result

    # ── Phase 5: generate from stage output ────────────────────────────

    async def generate_all_design_artifacts(
        self,
        task_id: str,
        stage_id: str,
        design_spec: str,
        project_name: str = "",
    ) -> Dict[str, Any]:
        """Generate all design visual artifacts from stage output.

        Returns dict with keys: mockup_result, design_tokens, screen_plan.
        """
        mockup_result = await self.generate_mockup(task_id, stage_id, design_spec, project_name)
        design_tokens = self.generate_design_tokens(design_spec)
        screen_plan = self.generate_screen_plan(design_spec)

        return {
            "mockup": mockup_result,
            "design_tokens": design_tokens,
            "screen_plan": screen_plan,
        }

    async def generate_all_architecture_artifacts(
        self,
        task_id: str,
        stage_id: str,
        arch_spec: str,
        project_name: str = "",
    ) -> Dict[str, Any]:
        """Generate all architecture visual artifacts + structured data from stage output.

        Returns dict with keys: diagram_result, mermaid_raw, api_contract, data_model, file_plan.
        """
        diagram_result = await self.generate_architecture_diagram(
            task_id, stage_id, arch_spec, project_name,
        )
        api_contract = self.generate_api_contract(arch_spec)
        data_model = self.generate_data_model(arch_spec)
        file_plan = self.generate_file_plan(arch_spec)

        ok, issues = self.check_architecture_consistency(api_contract, data_model, file_plan)

        return {
            "diagram": diagram_result,
            "api_contract": api_contract,
            "data_model": data_model,
            "file_plan": file_plan,
            "consistency_ok": ok,
            "consistency_issues": issues,
        }
