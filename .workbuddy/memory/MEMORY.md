## Agent Hub — Visual Generator Architecture (2026-05-07)

### Design stage → UI Mockup
- `UiVisualizer.generate_mockup()` for `design` stage
- Artifacts: `ui_mockup` (image), `ui_mockup_html` (HTML prototype)
- Tries Nano Banana Pro (Gemini 3 Pro Image), falls back to HTML only

### Architecture stage → Architecture Diagrams
- `UiVisualizer.generate_architecture_diagram()` for `architecture` stage
- Generates Mermaid.js diagrams: system overview (flowchart TD), sequence diagram, deployment view (flowchart LR)
- Artifact: `architecture_diagram` (HTML with Mermaid.js CDN rendering)
- Frontend: `TaskArchDiagram.vue` renders via iframe

### Pipeline Integration
- Layer 9.6 in `execute_stage()` — after LLM output, before artifact writer
- Custom artifact types bypass `STAGE_TO_ARTIFACT` mapping, use `_write_one_artifact` directly
- `_write_one_artifact` now supports `metadata_json` parameter
