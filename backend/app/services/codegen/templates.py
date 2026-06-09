"""
Project Templates — scaffolding for different app types.

Each template defines:
- Directory structure
- Boilerplate files
- Build/run commands
- Required dependencies

Template loading priority:
1. Inline ``files`` dict in ``PROJECT_TEMPLATES`` (overrides dir copy)
2. On-disk directory under ``packages/agent-hub-pipeline/templates/`` (fallback)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


_HERE = os.path.abspath(os.path.dirname(__file__))
# Resolve to packages/agent-hub-pipeline/templates/ (works in backend or root dev)
_PACKAGE_TEMPLATE_DIR = os.path.abspath(
    os.path.join(_HERE, "..", "..", "..", "..",
                 "packages", "agent-hub-pipeline", "templates")
)


def _load_template_files(template_id: str) -> Optional[Dict[str, str]]:
    """Load template files from on-disk directory.

    Returns None if no directory exists for this template.
    """
    tmpl_dir = os.path.join(_PACKAGE_TEMPLATE_DIR, template_id)
    if not os.path.isdir(tmpl_dir):
        return None
    files: Dict[str, str] = {}
    for root, _dirs, filenames in os.walk(tmpl_dir):
        for fn in filenames:
            full_path = os.path.join(root, fn)
            rel_path = os.path.relpath(full_path, tmpl_dir)
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    files[rel_path] = f.read()
            except Exception:
                # skip binary files (e.g. png placeholders)
                pass
    return files


PROJECT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "vue-app": {
        "name": "Vue 3 App",
        "description": "Vue 3 + Vite + TypeScript single-page application",
        "type": "web-app",
        "stack": ["vue3", "vite", "typescript", "pinia"],
        # files loaded from packages/agent-hub-pipeline/templates/vue-app/
        "files": {},
        "build_cmd": "pnpm install && pnpm build && pnpm test",
        "dev_cmd": "pnpm dev",
        "test_cmd": "pnpm test",
        "dockerfile": """FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",
    },
    "react-app": {
        "name": "React App",
        "description": "React 18 + Vite + TypeScript single-page application",
        "type": "web-app",
        "stack": ["react", "vite", "typescript"],
        "files": {
            "package.json": """{
  "name": "{{project_name}}",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6.23.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.4.0",
    "vite": "^5.4.0"
  }
}""",
            "index.html": """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{project_name}}</title>
</head>
<body>
  <div id="root"></div>
  <script type="module" src="/src/main.tsx"></script>
</body>
</html>""",
            "src/main.tsx": """import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
""",
            "src/App.tsx": """import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Home from './pages/Home'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
      </Routes>
    </BrowserRouter>
  )
}
""",
            "src/pages/Home.tsx": """export default function Home() {
  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: '2rem', textAlign: 'center' }}>
      <h1>{{project_name}}</h1>
      <p>Welcome to your new app.</p>
    </div>
  )
}
""",
        },
        "build_cmd": "npm install && npm run build",
        "dev_cmd": "npm run dev",
    },
    "fastapi-backend": {
        "name": "FastAPI Backend",
        "description": "Python FastAPI backend with async SQLAlchemy",
        "type": "backend",
        "stack": ["python", "fastapi", "sqlalchemy", "postgresql"],
        "files": {
            "requirements.txt": """fastapi>=0.111.0
uvicorn[standard]>=0.29.0
sqlalchemy[asyncio]>=2.0.30
asyncpg>=0.29.0
alembic>=1.13.0
pydantic>=2.7.0
pydantic-settings>=2.3.0
""",
            "app/main.py": """from fastapi import FastAPI

app = FastAPI(title="{{project_name}}")

@app.get("/")
async def root():
    return {"message": "Hello from {{project_name}}"}
""",
            "app/database.py": """from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

DATABASE_URL = "postgresql+asyncpg://user:pass@localhost:5432/db"
engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)
""",
            "app/models.py": """from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()
""",
        },
        "build_cmd": "pip install -r requirements.txt",
        "dev_cmd": "uvicorn app.main:app --reload --port 8000",
    },
    "wechat-miniapp": {
        "name": "WeChat Mini Program",
        "description": "WeChat mini-program with JavaScript + WXML + WXSS",
        "type": "mini-app",
        "stack": ["wechat", "javascript", "wxml", "wxss"],
        "files": {
            "app.js": """App({
  onLaunch() {
    console.log('App launched: {{project_name}}')
  }
})
""",
            "app.json": """{
  "pages": ["pages/index/index"],
  "window": {
    "navigationBarTitleText": "{{project_name}}"
  }
}
""",
            "app.wxss": """.container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
}
.title {
  font-size: 20px;
  font-weight: bold;
  margin-bottom: 10px;
}
""",
            "pages/index/index.js": """Page({
  data: {
    message: 'Hello from {{project_name}}'
  }
})
""",
            "pages/index/index.wxml": """<view class="container">
  <text class="title">{{project_name}}</text>
  <text>{{message}}</text>
</view>
""",
            "pages/index/index.wxss": """.container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
}
.title {
  font-size: 20px;
  font-weight: bold;
  margin-bottom: 10px;
}
""",
        },
        "build_cmd": "",
        "dev_cmd": "",
    },
}


def get_template(template_id: str) -> Optional[Dict[str, Any]]:
    return PROJECT_TEMPLATES.get(template_id)


def list_templates() -> List[Dict[str, str]]:
    return [
        {"id": k, "name": v["name"], "description": v["description"], "type": v["type"]}
        for k, v in PROJECT_TEMPLATES.items()
    ]


def scaffold_project(
    template_id: str,
    project_name: str,
    output_dir: str,
) -> Dict[str, Any]:
    """Write template files to output_dir with variable substitution.

    Priority:
    1. Inline ``files`` dict (if non-empty — used by react/fastapi/wechat templates)
    2. On-disk ``packages/agent-hub-pipeline/templates/{template_id}/`` (used by vue-app)
    """
    template = PROJECT_TEMPLATES.get(template_id)
    if not template:
        return {"ok": False, "error": f"Unknown template: {template_id}"}

    source_files = template.get("files") or {}
    if not source_files:
        dir_files = _load_template_files(template_id)
        if dir_files:
            source_files = dir_files

    if not source_files:
        return {"ok": False, "error": f"Template {template_id} has no files (inline or directory)"}

    os.makedirs(output_dir, exist_ok=True)
    written = []

    for rel_path, content in source_files.items():
        rendered = content.replace("{{project_name}}", project_name)
        full_path = os.path.join(output_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        if os.path.exists(full_path):
            logger.debug("[templates] Overwriting %s in %s", rel_path, output_dir)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(rendered)
        written.append(rel_path)

    dockerfile = template.get("dockerfile")
    if dockerfile:
        df_path = os.path.join(output_dir, "Dockerfile")
        with open(df_path, "w", encoding="utf-8") as f:
            f.write(dockerfile)
        written.append("Dockerfile")

    return {
        "ok": True,
        "template": template_id,
        "project_name": project_name,
        "files_written": written,
        "build_cmd": template.get("build_cmd", ""),
        "dev_cmd": template.get("dev_cmd", ""),
    }
