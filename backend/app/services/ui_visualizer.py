"""
UI Visualizer + Architecture Diagram Generator
================================================

Generates visual artifacts from pipeline stage outputs:

UI/Design stages:
    1. ``ui_mockup`` — PNG image of the UI design (via Nano Banana Pro)
    2. ``ui_mockup_html`` — Interactive HTML prototype

Architecture stages:
    1. ``architecture_diagram`` — Mermaid-based architecture diagrams (HTML)
       - System Architecture Overview (flowchart)
       - Data Flow Diagram (flowchart)
       - Sequence Diagrams for key flows
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


# ── UI Visualizer ──────────────────────────────────────────────────────


class UiVisualizer:
    """Generate visual UI mockups from pipeline design specs."""

    def __init__(self, workspace_root: str = "") -> None:
        self.workspace_root = workspace_root or os.environ.get(
            "WORKSPACE_ROOT", "/tmp/agent-hub-ui",
        )

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

        # 2. Gemini / Nano Banana Pro
        gemini_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
        banana_script = os.path.expanduser(
            "~/.workbuddy/skills/nano-banana-pro/scripts/generate_image.py",
        )
        if gemini_key and os.path.exists(banana_script):
            channels["gemini_nano_banana"] = {"available": True}
        else:
            missing = []
            if not gemini_key:
                missing.append("GEMINI_API_KEY")
            if not os.path.exists(banana_script):
                missing.append("nano-banana-pro script")
            channels["gemini_nano_banana"] = {"available": False, "reason": f"missing: {', '.join(missing)}"}
            if "nano-banana-pro script" not in missing:
                fallbacks.append("html_prototype")

        # 3. HTML prototype fallback
        try:
            self._generate_html(
                {"theme": "light", "primary_color": "#6366f1"},
                {"type": "dashboard"},
                ["header", "card", "footer"],
                "/tmp/_check_html_fallback",
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
        elif channels.get("html_prototype", {}).get("available"):
            fallbacks.append("html_prototype")

        overall_ok = (
            channels.get("openai_images", {}).get("available")
            or channels.get("gemini_nano_banana", {}).get("available")
            or channels.get("html_prototype", {}).get("available")
        )

        return {
            "ok": overall_ok,
            "channels": channels,
            "available": available_channel_names,
            "fallbacks": fallbacks,
        }

    async def check_diagram_resources(self) -> Dict[str, Any]:
        """Check availability of diagram generation resources for architect stage."""
        channels: Dict[str, Any] = {}
        fallbacks: List[str] = []

        # Mermaid rendering: local or CDN
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

        return {
            "ok": True,  # HTML rendering always works
            "channels": channels,
            "available": available,
            "fallbacks": fallbacks,
        }

    # ── Phase 5: Design Tokens & Screen Plan generation ────────────────

    @staticmethod
    def generate_design_tokens(design_spec: str) -> Dict[str, Any]:
        """Extract structured design tokens from spec (colors, typography, spacing)."""
        spec_lower = design_spec.lower()
        tokens: Dict[str, Any] = {}

        # Primary color
        primary = "#6366f1"  # default indigo
        import re
        colors = re.findall(r"#[0-9a-fA-F]{6}", design_spec)
        if colors:
            primary = colors[0]
        tokens["primary"] = primary

        # Secondary color
        secondary = "#059669"
        if len(colors) > 1:
            secondary = colors[1]
        tokens["secondary"] = secondary

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

        if "glass" in spec_lower or "frost" in spec_lower:
            tokens["style"] = "glassmorphism"
        elif "neon" in spec_lower or "cyber" in spec_lower:
            tokens["style"] = "dark neon"
        elif "minimal" in spec_lower:
            tokens["style"] = "minimal"

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

        return {
            "screens": screens,
            "state_matrix": {
                "loading": "Skeleton/spinner while data loads",
                "empty": "Empty state with CTA when no data",
                "error": "Error state with retry action",
                "success": "Normal data display with full UI",
            },
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

        # Entity names from api_contract
        api_entities: set = set()
        for endpoint in api_contract.get("endpoints", []):
            name = endpoint.get("entity", endpoint.get("resource", ""))
            if name:
                api_entities.add(name.lower())

        # Entity names from data_model
        model_entities: set = set()
        for table in data_model.get("tables", data_model.get("entities", [])):
            name = table.get("name", table.get("table", ""))
            if name:
                model_entities.add(name.lower())

        # Cross-check 1: API entity should exist in data model
        for ae in api_entities:
            ae_clean = ae.rstrip("s")  # plural API name
            ae_plural = ae + "s"  # singular API name
            if ae not in model_entities and ae_plural not in model_entities and ae_clean not in model_entities:
                issues.append(f"API entity '{ae}' not found in data model entities")

        # Cross-check 2: Routes from file_plan should have corresponding API routes
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

        # Check if file_plan directories map to route groups
        dir_mismatches = file_routes - api_routes
        if dir_mismatches and len(dir_mismatches) < len(file_routes):
            for dm in dir_mismatches:
                issues.append(f"File plan directory '{dm}' has no corresponding API route group")

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
            ``{"ok": True, "imagePath": "...", "htmlPath": "...", "prompt": "..."}``
        """
        out_dir = os.path.join(self.workspace_root, task_id, MOCKUP_DIR)
        os.makedirs(out_dir, exist_ok=True)

        # Extract style and layout from spec
        style, layout, components = self._parse_spec(design_spec)

        # 1. Generate mockup image (try Nano Banana Pro / Gemini API)
        image_path = await self._generate_image(
            design_spec, style, out_dir, task_id,
        )

        # 2. Generate interactive HTML prototype
        html_path = self._generate_html(
            style, layout, components, out_dir, project_name,
        )

        return {
            "ok": True,
            "imagePath": image_path or "",
            "htmlPath": html_path,
            "imageExists": bool(image_path),
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
        """Generate UI mockup image via Nano Banana Pro / Gemini API."""
        prompt = self._build_image_prompt(spec, style, {})

        # Try Nano Banana Pro script
        script = os.path.expanduser(
            "~/.workbuddy/skills/nano-banana-pro/scripts/generate_image.py",
        )
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")

        if os.path.exists(script) and api_key:
            try:
                filename = f"{datetime.utcnow().strftime('%Y-%m-%d-%H-%M-%S')}-ui-mockup.png"
                filepath = os.path.join(out_dir, filename)

                import subprocess
                result = subprocess.run(
                    ["uv", "run", script,
                     "--prompt", prompt,
                     "--filename", filepath,
                     "--resolution", "2K",
                     "--api-key", api_key],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode == 0 and os.path.exists(filepath):
                    logger.info("[ui-visualizer] Image generated: %s", filepath)
                    return filepath

                logger.warning("[ui-visualizer] Script failed: %s", result.stderr[:200])
            except Exception as e:
                logger.warning("[ui-visualizer] Image gen failed: %s", e)

        # Fallback: use the image_gen tool (available via agent runtime)
        # We store the prompt so the pipeline can call image_gen downstream
        return None

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

    def _parse_spec(self, spec: str) -> Tuple[Dict, Dict, List]:
        """Parse design spec to extract style, layout, and components."""
        spec_lower = spec.lower()

        # Theme detection
        style: Dict[str, Any] = {
            "theme": "dark" if "dark" in spec_lower else "light",
            "primary_color": self._extract_color(spec, "#6366f1"),
            "font": "Inter, system-ui, sans-serif",
        }

        if "minimal" in spec_lower:
            style["theme"] = "minimal light"
        elif "glass" in spec_lower or "frost" in spec_lower:
            style["theme"] = "glassmorphism"
        elif "neon" in spec_lower or "cyber" in spec_lower:
            style["theme"] = "dark neon"

        # Layout detection
        layout: Dict[str, Any] = {
            "type": "dashboard",
        }
        if "sidebar" in spec_lower:
            layout["type"] = "sidebar-layout"
        elif "single page" in spec_lower:
            layout["type"] = "single-page"
        elif "landing" in spec_lower:
            layout["type"] = "landing-page"
        elif "todo" in spec_lower or "kanban" in spec_lower:
            layout["type"] = "kanban-board"

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
        """Generate an interactive HTML prototype reflecting the design spec."""
        theme = style.get("theme", "light")
        primary = style.get("primary_color", "#6366f1")
        is_dark = "dark" in str(theme).lower()

        bg = "#0f0f1a" if is_dark else "#f8f9fa"
        surface = "#1a1a2e" if is_dark else "#ffffff"
        text_color = "#e2e8f0" if is_dark else "#1e293b"
        text_muted = "#94a3b8" if is_dark else "#64748b"

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
.mockup-frame {{ background: {surface}; border-radius: 16px; border: 1px solid {'rgba(255,255,255,0.08)' if is_dark else 'rgba(0,0,0,0.06)'}; overflow: hidden; min-height: 600px; }}
.toolbar {{ display: flex; align-items: center; gap: 12px; padding: 16px 24px; border-bottom: 1px solid {'rgba(255,255,255,0.06)' if is_dark else 'rgba(0,0,0,0.06)'}; }}
.toolbar-dot {{ width: 12px; height: 12px; border-radius: 50%; }}
.toolbar-dot:nth-child(1) {{ background: #ef4444; }}
.toolbar-dot:nth-child(2) {{ background: #f59e0b; }}
.toolbar-dot:nth-child(3) {{ background: #22c55e; }}
.toolbar-title {{ font-size: 13px; color: {text_muted}; margin-left: 8px; }}
.navbar {{ display: flex; align-items: center; justify-content: space-between; padding: 12px 24px; background: {surface}; border-bottom: 1px solid {'rgba(255,255,255,0.06)' if is_dark else 'rgba(0,0,0,0.06)'}; }}
.logo {{ font-weight: 700; font-size: 18px; color: {primary}; }}
.nav-links {{ display: flex; gap: 24px; }}
.nav-links a {{ color: {text_muted}; text-decoration: none; font-size: 14px; transition: color 0.2s; }}
.nav-links a:hover {{ color: {text_color}; }}
.content {{ display: grid; grid-template-columns: 240px 1fr; min-height: 600px; }}
.sidebar {{ padding: 24px; border-right: 1px solid {'rgba(255,255,255,0.06)' if is_dark else 'rgba(0,0,0,0.06)'}; }}
.sidebar-item {{ padding: 10px 16px; border-radius: 8px; margin-bottom: 4px; font-size: 14px; color: {text_muted}; cursor: pointer; transition: all 0.2s; }}
.sidebar-item:hover {{ background: {primary}15; color: {primary}; }}
.sidebar-item.active {{ background: {primary}; color: #fff; }}
.main {{ padding: 24px; }}
.header-row {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }}
.header-row h1 {{ font-size: 24px; font-weight: 600; }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
.stat-card {{ padding: 20px; border-radius: 12px; background: {surface}; border: 1px solid {'rgba(255,255,255,0.06)' if is_dark else 'rgba(0,0,0,0.06)'}; }}
.stat-card .label {{ font-size: 12px; color: {text_muted}; text-transform: uppercase; letter-spacing: 0.5px; }}
.stat-card .value {{ font-size: 28px; font-weight: 700; margin-top: 8px; color: {primary}; }}
.card-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }}
.card {{ padding: 20px; border-radius: 12px; background: {surface}; border: 1px solid {'rgba(255,255,255,0.06)' if is_dark else 'rgba(0,0,0,0.06)'}; transition: transform 0.2s; }}
.card:hover {{ transform: translateY(-2px); }}
.card h3 {{ font-size: 15px; margin-bottom: 8px; }}
.card p {{ font-size: 13px; color: {text_muted}; }}
.badge {{ display: inline-block; padding: 2px 10px; border-radius: 100px; font-size: 12px; background: {primary}15; color: {primary}; }}
.btn {{ display: inline-flex; align-items: center; gap: 6px; padding: 8px 20px; border-radius: 8px; font-size: 14px; font-weight: 500; cursor: pointer; border: none; transition: all 0.2s; }}
.btn-primary {{ background: {primary}; color: #fff; }}
.btn-primary:hover {{ opacity: 0.9; }}
.btn-outline {{ border: 1px solid {'rgba(255,255,255,0.15)' if is_dark else 'rgba(0,0,0,0.15)'}; background: transparent; color: {text_color}; }}
.btn-outline:hover {{ background: {'rgba(255,255,255,0.05)' if is_dark else 'rgba(0,0,0,0.03)'}; }}
.footer {{ text-align: center; padding: 24px; color: {text_muted}; font-size: 13px; border-top: 1px solid {'rgba(255,255,255,0.06)' if is_dark else 'rgba(0,0,0,0.06)'}; }}
@media (max-width: 768px) {{ .content {{ grid-template-columns: 1fr; }} .sidebar {{ display: none; }} }}
</style></head>
<body>
<div class="container">
  <div class="mockup-frame">
    <div class="toolbar">
      <span class="toolbar-dot"></span><span class="toolbar-dot"></span><span class="toolbar-dot"></span>
      <span class="toolbar-title">{project_name or 'UI Mockup'}</span>
    </div>
    <nav class="navbar">
      <div class="logo">{project_name[:4] if project_name else 'Hub'}</div>
      <div class="nav-links">
        <a href="#">Dashboard</a><a href="#">Projects</a><a href="#">Analytics</a><a href="#">Settings</a>
      </div>
    </nav>
    <div class="content">
      <aside class="sidebar">
        <div class="sidebar-item active">📊 Overview</div>
        <div class="sidebar-item">📁 Projects</div>
        <div class="sidebar-item">📈 Analytics</div>
        <div class="sidebar-item">👥 Team</div>
        <div class="sidebar-item">⚙️ Settings</div>
      </aside>
      <main class="main">
        <div class="header-row">
          <h1>Dashboard</h1>
          <button class="btn btn-primary">+ New Project</button>
        </div>
        <div class="stats">
          <div class="stat-card"><div class="label">Total Projects</div><div class="value">12</div></div>
          <div class="stat-card"><div class="label">Active Tasks</div><div class="value">48</div></div>
          <div class="stat-card"><div class="label">Team Members</div><div class="value">8</div></div>
          <div class="stat-card"><div class="label">Completion</div><div class="value">87%</div></div>
        </div>
        <div class="card-grid">
          <div class="card"><h3>Project Alpha</h3><p>Frontend redesign with modern UI patterns</p><span class="badge">In Progress</span></div>
          <div class="card"><h3>Project Beta</h3><p>Backend API optimization and migration</p><span class="badge">Review</span></div>
          <div class="card"><h3>Project Gamma</h3><p>Mobile app v2 with new features</p><span class="badge">Done</span></div>
        </div>
      </main>
    </div>
    <div class="footer">Agent Hub · AI 生成的 UI 设计稿 · {datetime.utcnow().strftime('%Y-%m-%d')}</div>
  </div>
</div>
</body>
</html>"""

        filename = f"{datetime.utcnow().strftime('%Y-%m-%d-%H-%M-%S')}-ui-prototype.html"
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

        Returns:
            ``{"ok": True, "htmlPath": "...", "mermaidRaw": "...", "summary": {...}}``
        """
        out_dir = os.path.join(self.workspace_root, task_id, ARCH_DIR)
        os.makedirs(out_dir, exist_ok=True)

        # Parse spec to extract components and flows
        components, flows = self._parse_architecture_spec(arch_spec)

        # Generate Mermaid markdown for multiple diagram types
        diagrams = self._generate_mermaid_diagrams(arch_spec, components, flows)

        # Generate HTML with Mermaid.js rendering
        html_path = self._generate_arch_html(
            diagrams, components, out_dir, project_name or "System Architecture",
        )

        return {
            "ok": True,
            "htmlPath": html_path,
            "mermaidRaw": diagrams,
            "componentCount": len(components),
            "flowCount": len(flows),
        }

    # ── Architecture Spec Parsing ─────────────────────────────────────

    def _parse_architecture_spec(
        self,
        spec: str,
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """Parse architecture spec to extract system components and data flows."""
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
                    # Extract description context (first sentence mentioning this component)
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

        if not components:
            # Fallback: default web app stack
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

        return components, flows

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

    def _generate_arch_html(
        self,
        diagrams: Dict[str, str],
        components: List[Dict[str, str]],
        out_dir: str,
        project_name: str,
    ) -> str:
        """Wrap Mermaid diagrams in a standalone HTML page."""
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

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{project_name} — 架构图</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    background: #0f0f1a;
    color: #e2e8f0;
    line-height: 1.6;
}}
.header {{
    padding: 24px 32px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    display: flex;
    align-items: center;
    gap: 12px;
}}
.header h1 {{ font-size: 20px; font-weight: 600; }}
.header .subtitle {{ color: #94a3b8; font-size: 13px; }}
.diagram-section {{
    padding: 24px 32px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
}}
.diagram-section:last-child {{ border-bottom: none; }}
.section-title {{
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
}}
.section-title .tag {{
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 100px;
    background: rgba(99,102,241,0.15);
    color: #818cf8;
    font-weight: 500;
}}
.mermaid-container {{
    background: #1a1a2e;
    border-radius: 12px;
    border: 1px solid rgba(255,255,255,0.08);
    padding: 24px;
    overflow-x: auto;
    min-height: 300px;
    display: flex;
    justify-content: center;
}}
.mermaid-container svg {{ max-width: 100%; height: auto; }}
.component-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 12px;
    margin: 16px 0;
}}
.component-card {{
    padding: 14px 16px;
    border-radius: 10px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
}}
.component-card .name {{ font-weight: 500; font-size: 14px; }}
.component-card .desc {{ font-size: 12px; color: #94a3b8; margin-top: 4px; }}
.footer {{
    text-align: center;
    padding: 20px;
    color: #4b5563;
    font-size: 12px;
}}
@media (max-width: 768px) {{
    .diagram-section {{ padding: 16px; }}
    .header {{ padding: 16px; flex-direction: column; align-items: flex-start; }}
}}
</style>
</head>
<body>
<div class="header">
    <h1>{project_name}</h1>
    <span class="subtitle">系统架构图 · AI 自动生成</span>
</div>
<div class="diagram-section">
    <div class="section-title">
        📐 系统架构总览 <span class="tag">Architecture Overview</span>
    </div>
    <div class="mermaid-container">
        <pre class="mermaid">
{diagrams['architecture']}
        </pre>
    </div>
</div>
<div class="diagram-section">
    <div class="section-title">
        🔄 核心交互流程 <span class="tag">Sequence Diagram</span>
    </div>
    <div class="mermaid-container">
        <pre class="mermaid">
{diagrams['sequence']}
        </pre>
    </div>
</div>
<div class="diagram-section">
    <div class="section-title">
        🏗️ 分层部署视图 <span class="tag">Deployment View</span>
    </div>
    <div class="mermaid-container">
        <pre class="mermaid">
{diagrams['deployment']}
        </pre>
    </div>
</div>
<div class="diagram-section">
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
<script>
mermaid.initialize(""" + json.dumps(mermaid_config) + """);
</script>
</body>
</html>"""

        filename = f"{datetime.utcnow().strftime('%Y-%m-%d-%H-%M-%S')}-architecture.html"
        filepath = os.path.join(out_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("[ui-visualizer] Architecture diagram: %s", filepath)
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

        if not entities:
            entities = ["item"]

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

        return {"endpoints": endpoints}

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

        if not tables:
            tables.append({
                "name": "items",
                "description": "Generic items",
                "fields": [
                    {"name": "id", "type": "uuid", "pk": True},
                    {"name": "name", "type": "varchar(200)"},
                    {"name": "created_at", "type": "timestamp"},
                ],
            })

        return {"tables": tables}

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

        if not directories:
            directories.append({"name": "src", "description": "Source code"})

        return {"directories": directories, "files": [{"name": d["name"]} for d in directories]}

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
