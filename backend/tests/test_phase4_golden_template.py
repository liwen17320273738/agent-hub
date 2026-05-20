"""
Phase 4 Golden Template Scorecard — 10 fixed requirements benchmark.

Runs without real LLM: scaffolds vue-app template, writes pre-built Vue SFC
components, runs real ``pnpm install && pnpm build && pnpm test``, and
verifies ``source_manifest.json`` + ``build.log`` existence.

Score target: ≥ 8/10 PASS
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Set

import pytest

from app.services.codegen.templates import scaffold_project, get_template
from app.services.codegen.codegen_agent import _build_source_manifest


# ── 10 fixed requirements ──────────────────────────────────────────
_REQUIREMENTS: List[Dict[str, str]] = [
    {
        "id": "todo-app",
        "title": "待办事项",
        "component": "TodoApp",
        "sfc": """<template>
  <div class="todo-app">
    <h1>待办事项</h1>
    <div class="add-todo">
      <input v-model="newTodo" @keyup.enter="addTodo" placeholder="新增待办..." />
      <button @click="addTodo">添加</button>
    </div>
    <div class="todo-list">
      <div v-for="todo in todos" :key="todo.id" class="todo-item" :class="{done: todo.done}">
        <input type="checkbox" v-model="todo.done" />
        <span>{{ todo.text }}</span>
        <button @click="deleteTodo(todo.id)">删除</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
interface Todo { id: number; text: string; done: boolean }
const newTodo = ref('')
const todos = ref<Todo[]>([])
function addTodo() {
  if (!newTodo.value.trim()) return
  todos.value.push({ id: Date.now(), text: newTodo.value, done: false })
  newTodo.value = ''
}
function deleteTodo(id: number) {
  todos.value = todos.value.filter(t => t.id !== id)
}
</script>""",
    },
    {
        "id": "counter",
        "title": "计数器",
        "component": "CounterApp",
        "sfc": """<template>
  <div class="counter">
    <h1>计数器</h1>
    <div class="count">{{ count }}</div>
    <div class="actions">
      <button @click="count--">-1</button>
      <button @click="count=0">重置</button>
      <button @click="count++">+1</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
const count = ref(0)
</script>""",
    },
    {
        "id": "weather-card",
        "title": "天气卡片",
        "component": "WeatherCard",
        "sfc": """<template>
  <div class="weather-card">
    <h2>{{ city }}</h2>
    <div class="temp">{{ temperature }}°C</div>
    <div class="detail">湿度: {{ humidity }}%</div>
    <div class="detail">风速: {{ windSpeed }} km/h</div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
const city = ref('北京')
const temperature = ref(22)
const humidity = ref(65)
const windSpeed = ref(12)
</script>""",
    },
    {
        "id": "quote-generator",
        "title": "名言生成器",
        "component": "QuoteGenerator",
        "sfc": """<template>
  <div class="quote-generator">
    <blockquote>{{ currentQuote.text }}</blockquote>
    <cite>— {{ currentQuote.author }}</cite>
    <button @click="randomQuote">随机名言</button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
interface Quote { text: string; author: string }
const quotes: Quote[] = [
  { text: '知行合一', author: '王阳明' },
  { text: 'Hello World', author: 'Brian Kernighan' },
  { text: 'Keep it simple', author: 'Unix Philosophy' },
]
const currentQuote = ref(quotes[0])
function randomQuote() {
  currentQuote.value = quotes[Math.floor(Math.random() * quotes.length)]
}
</script>""",
    },
    {
        "id": "countdown",
        "title": "倒计时",
        "component": "CountdownTimer",
        "sfc": """<template>
  <div class="countdown">
    <h1>倒计时</h1>
    <div class="target">
      <input v-model="targetDate" type="date" />
      <button @click="startCountdown">开始</button>
    </div>
    <div v-if="timeLeft" class="display">
      <span>{{ timeLeft.days }}天</span>
      <span>{{ timeLeft.hours }}时</span>
      <span>{{ timeLeft.minutes }}分</span>
      <span>{{ timeLeft.seconds }}秒</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
const targetDate = ref('')
const timeLeft = ref<{days:number;hours:number;minutes:number;seconds:number}|null>(null)
let timer: ReturnType<typeof setInterval> | null = null
function startCountdown() {
  if (!targetDate.value) return
  const target = new Date(targetDate.value).getTime()
  timer = setInterval(() => {
    const diff = target - Date.now()
    if (diff <= 0) { timeLeft.value = null; clearInterval(timer!); return }
    timeLeft.value = {
      days: Math.floor(diff / 86400000),
      hours: Math.floor((diff % 86400000) / 3600000),
      minutes: Math.floor((diff % 3600000) / 60000),
      seconds: Math.floor((diff % 60000) / 1000),
    }
  }, 1000)
}
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>""",
    },
    {
        "id": "color-tool",
        "title": "配色工具",
        "component": "ColorTool",
        "sfc": """<template>
  <div class="color-tool">
    <h1>配色工具</h1>
    <input v-model="color" type="color" />
    <div class="preview" :style="{background: color}"></div>
    <div class="values">
      <p>HEX: {{ color }}</p>
      <p>RGB: {{ hexToRgb(color) }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
const color = ref('#3370ff')
function hexToRgb(hex: string): string {
  const r = parseInt(hex.slice(1,3), 16)
  const g = parseInt(hex.slice(3,5), 16)
  const b = parseInt(hex.slice(5,7), 16)
  return `rgb(${r}, ${g}, ${b})`
}
</script>""",
    },
    {
        "id": "notes-list",
        "title": "笔记列表",
        "component": "NotesList",
        "sfc": """<template>
  <div class="notes-list">
    <h1>笔记</h1>
    <div class="note-form">
      <input v-model="title" placeholder="标题" />
      <textarea v-model="content" placeholder="内容"></textarea>
      <button @click="addNote">保存</button>
    </div>
    <div v-for="note in notes" :key="note.id" class="note-card">
      <h3>{{ note.title }}</h3>
      <p>{{ note.content }}</p>
      <button @click="deleteNote(note.id)">删除</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
interface Note { id: number; title: string; content: string }
const title = ref('')
const content = ref('')
const notes = ref<Note[]>([])
function addNote() {
  if (!title.value.trim()) return
  notes.value.push({ id: Date.now(), title: title.value, content: content.value })
  title.value = ''
  content.value = ''
}
function deleteNote(id: number) {
  notes.value = notes.value.filter(n => n.id !== id)
}
</script>""",
    },
    {
        "id": "pomodoro",
        "title": "番茄钟",
        "component": "PomodoroTimer",
        "sfc": """<template>
  <div class="pomodoro">
    <h1>番茄钟</h1>
    <div class="timer">{{ formattedTime }}</div>
    <div class="controls">
      <button v-if="!isRunning" @click="start">开始</button>
      <button v-else @click="pause">暂停</button>
      <button @click="reset">重置</button>
    </div>
    <div class="count">已完成: {{ completed }} 轮</div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
const WORK_TIME = 25 * 60
const timeLeft = ref(WORK_TIME)
const isRunning = ref(false)
const completed = ref(0)
let timer: ReturnType<typeof setInterval> | null = null
const formattedTime = computed(() => {
  const m = Math.floor(timeLeft.value / 60)
  const s = timeLeft.value % 60
  return `${m.toString().padStart(2,'0')}:${s.toString().padStart(2,'0')}`
})
function start() {
  isRunning.value = true
  timer = setInterval(() => {
    timeLeft.value--
    if (timeLeft.value <= 0) {
      clearInterval(timer!); isRunning.value = false
      completed.value++; timeLeft.value = WORK_TIME
    }
  }, 1000)
}
function pause() {
  isRunning.value = false
  if (timer) clearInterval(timer)
}
function reset() {
  pause(); timeLeft.value = WORK_TIME
}
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>""",
    },
    {
        "id": "bookmarks",
        "title": "书签管理",
        "component": "BookmarkManager",
        "sfc": """<template>
  <div class="bookmark-manager">
    <h1>书签管理</h1>
    <div class="form">
      <input v-model="name" placeholder="名称" />
      <input v-model="url" placeholder="URL" />
      <button @click="addBookmark">添加</button>
    </div>
    <div v-for="bm in bookmarks" :key="bm.id" class="bookmark-item">
      <a :href="bm.url" target="_blank">{{ bm.name }}</a>
      <button @click="deleteBookmark(bm.id)">删除</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
interface Bookmark { id: number; name: string; url: string }
const name = ref('')
const url = ref('')
const bookmarks = ref<Bookmark[]>([])
function addBookmark() {
  if (!name.value.trim() || !url.value.trim()) return
  bookmarks.value.push({ id: Date.now(), name: name.value, url: url.value })
  name.value = ''; url.value = ''
}
function deleteBookmark(id: number) {
  bookmarks.value = bookmarks.value.filter(b => b.id !== id)
}
</script>""",
    },
    {
        "id": "daily-checkin",
        "title": "每日打卡",
        "component": "DailyCheckin",
        "sfc": """<template>
  <div class="daily-checkin">
    <h1>每日打卡</h1>
    <p class="date">{{ today }}</p>
    <div class="progress">{{ doneCount }}/{{ items.length }}</div>
    <div v-for="item in items" :key="item.id" class="checkin-item" :class="{done: item.done}">
      <input type="checkbox" v-model="item.done" />
      <span>{{ item.label }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
interface Habit { id: number; label: string; done: boolean }
const today = new Date().toLocaleDateString('zh-CN')
const items = ref<Habit[]>([
  { id: 1, label: '早起', done: false },
  { id: 2, label: '阅读', done: false },
  { id: 3, label: '运动', done: false },
  { id: 4, label: '喝水', done: false },
])
const doneCount = computed(() => items.value.filter(i => i.done).length)
</script>""",
    },
]


# ── Helpers ─────────────────────────────────────────────────────────

def _scaffold_and_capture_baseline(req_dir: str, req: Dict[str, str]) -> Set[str]:
    """Scaffold vue-app template and return the set of files created."""
    result = scaffold_project("vue-app", req["title"], req_dir)
    assert result.get("ok"), f"scaffold: {result.get('error')}"
    return set(result.get("files_written", []))


def _write_component_and_update_router(req_dir: str, req: Dict[str, str]) -> None:
    """Write the custom Vue SFC and patch router to use it."""
    comp = req["component"]
    views_dir = os.path.join(req_dir, "src", "views")

    # Write SFC
    sfc_path = os.path.join(views_dir, f"{comp}.vue")
    with open(sfc_path, "w", encoding="utf-8") as f:
        f.write(req["sfc"])

    # Patch router
    router_path = os.path.join(req_dir, "src", "router", "index.ts")
    if os.path.isfile(router_path):
        with open(router_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace(
            "import Home from '../views/Home.vue'",
            f"import {comp} from '../views/{comp}.vue'",
        )
        content = content.replace(
            "{ path: '/', component: Home }",
            f"{{ path: '/', component: {comp} }}",
        )
        with open(router_path, "w", encoding="utf-8") as f:
            f.write(content)

    # Remove default Home.vue (if different from our component)
    home_path = os.path.join(views_dir, "Home.vue")
    if os.path.isfile(home_path) and comp != "Home":
        os.remove(home_path)
    # Also try HomeView.vue
    homeview_path = os.path.join(views_dir, "HomeView.vue")
    if os.path.isfile(homeview_path) and comp not in ("Home", "HomeView"):
        os.remove(homeview_path)


def _run_build(req_dir: str, timeout: int = 180) -> subprocess.CompletedProcess:
    """Run pnpm install, build, test sequentially."""
    cmds = [
        ["pnpm", "install"],
        ["pnpm", "build"],
        ["pnpm", "test"],
    ]
    last = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    for cmd in cmds:
        last = subprocess.run(cmd, cwd=req_dir, capture_output=True, text=True, timeout=timeout)
        if last.returncode != 0:
            break
    return last


def _write_artifacts(req_dir: str, req: Dict[str, str], baseline: Set[str],
                     build_out: subprocess.CompletedProcess) -> None:
    """Write source_manifest.json and build.log."""
    # build.log
    log_path = os.path.join(req_dir, "build.log")
    full_output = f"stdout:\n{build_out.stdout}\nstderr:\n{build_out.stderr}"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(full_output)

    # source_manifest.json
    template_obj = get_template("vue-app")
    build_cmd = template_obj.get("build_cmd", "") if template_obj else ""
    dev_cmd = template_obj.get("dev_cmd", "") if template_obj else ""
    test_cmd = "pnpm test"

    manifest = _build_source_manifest(
        req_dir, baseline, build_cmd, dev_cmd, test_cmd, build_out.returncode == 0,
    )
    manifest_path = os.path.join(req_dir, "source_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def pnpm_available() -> bool:
    """Check if pnpm is on PATH."""
    try:
        subprocess.run(["pnpm", "--version"], capture_output=True, check=True, timeout=10)
        return True
    except (subprocess.FileNotFoundError, subprocess.CalledProcessError, Exception):
        return False


@pytest.fixture(scope="session")
def sandbox_root() -> str:
    """Create a session-scoped sandbox directory."""
    tmpdir = tempfile.mkdtemp(prefix="phase4-")
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


# ── Core runner ─────────────────────────────────────────────────────

def _run_requirement(req_dir: str, req: Dict[str, str]) -> Dict[str, Any]:
    """Run a single requirement end-to-end.

    Steps:
    1. Scaffold vue-app template
    2. Capture file baseline
    3. Write custom Vue SFC + patch router
    4. pnpm install & build & test
    5. Write source_manifest.json + build.log
    6. Assert all three conditions
    """
    result: Dict[str, Any] = {
        "id": req["id"],
        "title": req["title"],
        "passed": False,
        "build_ok": False,
        "manifest_ok": False,
        "log_ok": False,
        "error": "",
    }

    try:
        os.makedirs(req_dir, exist_ok=True)

        # Step 1-2: Scaffold + baseline
        baseline = _scaffold_and_capture_baseline(req_dir, req)

        # Step 3: Write custom component
        _write_component_and_update_router(req_dir, req)

        # Step 4: Build
        build_out = _run_build(req_dir)
        result["build_ok"] = build_out.returncode == 0

        # Step 5: Write artifacts
        _write_artifacts(req_dir, req, baseline, build_out)

        # Step 6: Verify
        manifest_path = os.path.join(req_dir, "source_manifest.json")
        log_path = os.path.join(req_dir, "build.log")
        result["manifest_ok"] = os.path.isfile(manifest_path)
        result["log_ok"] = os.path.isfile(log_path)

        if result["build_ok"] and result["manifest_ok"] and result["log_ok"]:
            result["passed"] = True
        else:
            errors = []
            if not result["build_ok"]:
                err_tail = (build_out.stderr or build_out.stdout or "")[-300:].strip()
                result["error"] = f"build failed (exit={build_out.returncode}): {err_tail[:200]}"
                errors.append(result["error"])
            if not result["manifest_ok"]:
                errors.append("manifest missing")
            if not result["log_ok"]:
                errors.append("log missing")
            if not result["error"]:
                result["error"] = "; ".join(errors)

    except subprocess.TimeoutExpired:
        result["error"] = "build timeout"
    except AssertionError as e:
        result["error"] = str(e)[:200]
    except Exception as e:
        result["error"] = f"unexpected: {str(e)[:200]}"

    return result


# ── Tests ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("req", [
    pytest.param(r, id=r["id"]) for r in _REQUIREMENTS
])
def test_single_requirement(pnpm_available, sandbox_root, req):
    """Run one requirement as an independent test."""
    if not pnpm_available:
        pytest.skip("pnpm not available — cannot run real build")

    req_dir = os.path.join(sandbox_root, req["id"])
    result = _run_requirement(req_dir, req)
    assert result["passed"], f"{req['title']}: {result.get('error', '?')}"


def _print_scorecard(results: List[Dict[str, Any]]) -> None:
    print("\nPhase 4 Scorecard")
    print("=" * 60)
    for idx, r in enumerate(results, 1):
        status = "PASS" if r.get("passed") else "FAIL"
        icon = "✅" if r.get("passed") else "❌"
        build = "ok" if r.get("build_ok") else "failed"
        manifest = "ok" if r.get("manifest_ok") else "missing"
        log = "ok" if r.get("log_ok") else "missing"
        err = f" ({r.get('error', '')[:80]})" if r.get("error") else ""
        print(f"  {idx}. {r.get('title','?')}  {icon} {status} (build={build}, manifest={manifest}, log={log}){err}")


@pytest.mark.scorecard
def test_aggregate_scorecard(pnpm_available, sandbox_root):
    """Run all requirements and assert ≥ 8 pass."""
    if not pnpm_available:
        pytest.skip("pnpm not available — cannot run real build")

    results: List[Dict[str, Any]] = []
    for req in _REQUIREMENTS:
        req_dir = os.path.join(sandbox_root, req["id"])
        result = _run_requirement(req_dir, req)
        results.append(result)

    _print_scorecard(results)
    passes = sum(1 for r in results if r.get("passed"))
    print(f"\nScore: {passes}/{len(results)}  (target: ≥ 8)")

    # Show pass/fail per requirement
    for idx, r in enumerate(results, 1):
        if not r.get("passed"):
            print(f"  FAIL: {r['title']} — {r.get('error', '?')}")

    assert passes >= 8, f"Phase 4 scorecard: {passes}/{len(results)} — need ≥ 8"
