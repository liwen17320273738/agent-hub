"""Delivery docs API — same contract as server/deliveryDocs.mjs (docs/delivery/*.md)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..security import get_current_user
from ..models.user import User

router = APIRouter(prefix="/delivery-docs", tags=["delivery-docs"])

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DELIVERY_DIR = _REPO_ROOT / "docs" / "delivery"

_DELIVERY_SPECS: List[dict[str, str]] = [
    {
        "name": "01-prd.md",
        "title": "PRD",
        "description": "背景、目标、范围、非目标、用户故事、验收标准、开放问题。",
        "template": """# PRD：<标题>

- 版本 / 日期：

## 背景与目标

## 用户与场景

## 范围与非目标

## 用户故事与验收标准

## 里程碑

## 开放问题

## 与规则基线的注意点
""",
    },
    {
        "name": "02-ui-spec.md",
        "title": "UI Spec",
        "description": "页面、组件、状态、关键交互与异常流说明。",
        "template": """# UI Spec：<标题>

## 页面清单

## 关键流程

## 组件与布局

## 状态设计

## 异常态 / 空态 / 加载态

## 可访问性与还原注意点
""",
    },
    {
        "name": "03-architecture.md",
        "title": "Architecture",
        "description": "边界、契约、数据流、风险、失败路径与 ADR。",
        "template": """# Architecture：<标题>

## 上下文与边界

## 模块划分

## API / 契约

## 数据与状态

## 失败路径与观测

## ADR
""",
    },
    {
        "name": "04-implementation-notes.md",
        "title": "Implementation Notes",
        "description": "实现顺序、入口路径、配置、验证方式、偏差与回滚注意。",
        "template": """# Implementation Notes：<标题>

## 实现范围

## 修改点

## 入口路径 / 环境变量 / 开关

## 验证方式

## 已知偏差

## 回滚注意
""",
    },
    {
        "name": "05-test-report.md",
        "title": "Test Report",
        "description": "测试范围、已执行项、未执行项、风险与结论。",
        "template": """# Test Report：<标题>

## 测试范围

## 已执行

## 未执行 / 阻塞项

## 发现的问题

## 风险评估

## 结论
""",
    },
    {
        "name": "06-acceptance.md",
        "title": "Acceptance",
        "description": "验收结论、发布建议、回滚和监控检查项。",
        "template": """# Acceptance：<标题>

## 验收结论

## 发布说明

## 回滚方案

## 监控检查项

## 已知问题
""",
    },
]

_ALLOWED = {s["name"] for s in _DELIVERY_SPECS}

STAGE_TO_DOC = {
    "planning": "01-prd.md",
    "architecture": "03-architecture.md",
    "development": "04-implementation-notes.md",
    "testing": "05-test-report.md",
    "reviewing": "06-acceptance.md",
    "deployment": "04-implementation-notes.md",
}


async def write_stage_output(stage_id: str, content: str) -> None:
    """Write pipeline stage output to the corresponding delivery doc (no auth)."""
    doc_name = STAGE_TO_DOC.get(stage_id)
    if not doc_name:
        return

    def _write() -> None:
        _DELIVERY_DIR.mkdir(parents=True, exist_ok=True)
        (_DELIVERY_DIR / doc_name).write_text(content, encoding="utf-8")

    await asyncio.to_thread(_write)


def _ensure_dir() -> None:
    _DELIVERY_DIR.mkdir(parents=True, exist_ok=True)


async def _ensure_templates() -> None:
    def _write_missing() -> None:
        _ensure_dir()
        for spec in _DELIVERY_SPECS:
            path = _DELIVERY_DIR / spec["name"]
            if not path.exists():
                path.write_text(spec["template"], encoding="utf-8")

    await asyncio.to_thread(_write_missing)


async def _list_docs() -> list[dict[str, Any]]:
    await _ensure_templates()

    def _scan() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for spec in _DELIVERY_SPECS:
            path = _DELIVERY_DIR / spec["name"]
            if path.exists():
                mtime = path.stat().st_mtime * 1000
                out.append(
                    {
                        "name": spec["name"],
                        "title": spec["title"],
                        "description": spec["description"],
                        "exists": True,
                        "updatedAt": mtime,
                    }
                )
            else:
                out.append(
                    {
                        "name": spec["name"],
                        "title": spec["title"],
                        "description": spec["description"],
                        "exists": False,
                        "updatedAt": None,
                    }
                )
        return out

    return await asyncio.to_thread(_scan)


@router.get("", include_in_schema=False)
@router.get("/")
async def list_delivery_docs(_user: Annotated[User, Depends(get_current_user)]):
    docs = await _list_docs()
    return {"docs": docs}


@router.post("/init")
async def init_delivery_docs(_user: Annotated[User, Depends(get_current_user)]):
    await _ensure_templates()
    docs = await _list_docs()
    return {"docs": docs}


@router.get("/{name}")
async def read_delivery_doc(
    name: str,
    _user: Annotated[User, Depends(get_current_user)],
):
    if name not in _ALLOWED or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=404, detail="文档不存在")
    await _ensure_templates()
    path = (_DELIVERY_DIR / name).resolve()
    if not str(path).startswith(str(_DELIVERY_DIR.resolve())):
        raise HTTPException(status_code=403, detail="路径越权")

    def _read() -> tuple[str, float]:
        if not path.exists():
            raise FileNotFoundError
        return path.read_text(encoding="utf-8"), path.stat().st_mtime * 1000

    try:
        content, updated = await asyncio.to_thread(_read)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="文档不存在") from None
    meta = next(s for s in _DELIVERY_SPECS if s["name"] == name)
    return {
        "name": name,
        "title": meta["title"],
        "description": meta["description"],
        "content": content,
        "updatedAt": updated,
    }


class WriteBody(BaseModel):
    content: str = ""


@router.put("/{name}")
async def write_delivery_doc(
    name: str,
    body: WriteBody,
    _user: Annotated[User, Depends(get_current_user)],
):
    if name not in _ALLOWED or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=404, detail="文档不存在")
    _ensure_dir()
    path = (_DELIVERY_DIR / name).resolve()
    if not str(path).startswith(str(_DELIVERY_DIR.resolve())):
        raise HTTPException(status_code=403, detail="路径越权")

    def _write() -> float:
        path.write_text(body.content, encoding="utf-8")
        return path.stat().st_mtime * 1000

    updated = await asyncio.to_thread(_write)
    meta = next(s for s in _DELIVERY_SPECS if s["name"] == name)
    return {
        "name": name,
        "title": meta["title"],
        "description": meta["description"],
        "content": body.content,
        "updatedAt": updated,
    }
