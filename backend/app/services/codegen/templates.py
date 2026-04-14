"""
Project Templates — scaffolding for different app types.

Each template defines:
- Directory structure
- Boilerplate files
- Build/run commands
- Required dependencies
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "vue-app": {
        "name": "Vue 3 App",
        "description": "Vue 3 + Vite + TypeScript single-page application",
        "type": "web-app",
        "stack": ["vue3", "vite", "typescript", "pinia"],
        "files": {
            "package.json": """{
  "name": "{{project_name}}",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.3.0",
    "pinia": "^2.1.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "typescript": "^5.4.0",
    "vite": "^5.4.0",
    "vue-tsc": "^2.0.0"
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
  <div id="app"></div>
  <script type="module" src="/src/main.ts"></script>
</body>
</html>""",
            "src/main.ts": """import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
""",
            "src/App.vue": """<template>
  <router-view />
</template>
""",
            "src/router/index.ts": """import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('../views/Home.vue') },
  ],
})
export default router
""",
            "src/views/Home.vue": """<template>
  <div class="home">
    <h1>{{project_name}}</h1>
    <p>Welcome to your new app.</p>
  </div>
</template>

<style scoped>
.home {
  max-width: 800px;
  margin: 0 auto;
  padding: 2rem;
  text-align: center;
}
</style>
""",
            "vite.config.ts": """import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: { port: 3000 },
})
""",
            "tsconfig.json": """{
  "compilerOptions": {
    "target": "ES2020",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "jsx": "preserve",
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["src/**/*.ts", "src/**/*.vue"]
}""",
        },
        "build_cmd": "npm install && npm run build",
        "dev_cmd": "npm run dev",
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
uvicorn[standard]>=0.30.0
sqlalchemy[asyncio]>=2.0.30
asyncpg>=0.29.0
pydantic>=2.7.0
python-dotenv>=1.0.0
""",
            "app/__init__.py": "",
            "app/main.py": """from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="{{project_name}}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "{{project_name}}"}

@app.get("/api/hello")
async def hello():
    return {"message": "Hello from {{project_name}}!"}
""",
        },
        "build_cmd": "pip install -r requirements.txt",
        "dev_cmd": "uvicorn app.main:app --reload --port 8000",
    },
    "wechat-miniprogram": {
        "name": "WeChat Mini Program",
        "description": "微信小程序项目模板",
        "type": "miniprogram",
        "stack": ["wechat", "javascript"],
        "files": {
            "app.json": """{
  "pages": ["pages/index/index"],
  "window": {
    "backgroundTextStyle": "light",
    "navigationBarBackgroundColor": "#fff",
    "navigationBarTitleText": "{{project_name}}",
    "navigationBarTextStyle": "black"
  }
}""",
            "app.js": """App({
  onLaunch() {
    console.log('App launched');
  },
  globalData: {}
})
""",
            "app.wxss": """page {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 14px;
  color: #333;
}
""",
            "pages/index/index.js": """Page({
  data: {
    message: 'Hello {{project_name}}!'
  },
  onLoad() {}
})
""",
            "pages/index/index.wxml": """<view class="container">
  <text class="title">{{message}}</text>
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
  font-size: 24px;
  font-weight: bold;
}
""",
            "project.config.json": """{
  "description": "{{project_name}}",
  "packOptions": { "ignore": [], "include": [] },
  "setting": {
    "urlCheck": true,
    "es6": true,
    "enhance": true,
    "postcss": true,
    "preloadBackgroundData": false,
    "minified": true,
    "newFeature": false,
    "coverView": true,
    "nodeModules": false,
    "autoAudits": false,
    "showShadowRootInWxmlPanel": true
  },
  "compileType": "miniprogram"
}""",
        },
        "build_cmd": "echo 'Use WeChat DevTools to build'",
        "dev_cmd": "echo 'Open project in WeChat DevTools'",
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
    """Write template files to output_dir with variable substitution."""
    template = PROJECT_TEMPLATES.get(template_id)
    if not template:
        return {"ok": False, "error": f"Unknown template: {template_id}"}

    os.makedirs(output_dir, exist_ok=True)
    written = []

    for rel_path, content in template["files"].items():
        rendered = content.replace("{{project_name}}", project_name)
        full_path = os.path.join(output_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
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
