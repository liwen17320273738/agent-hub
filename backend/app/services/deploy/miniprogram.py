"""WeChat Mini Program deployment via miniprogram-ci."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Any, Dict, Optional

from ..sse import emit_event

logger = logging.getLogger(__name__)


async def deploy_miniprogram(
    *,
    project_dir: str,
    app_id: str,
    private_key_path: str,
    version: str = "1.0.0",
    description: str = "Agent Hub auto deploy",
    robot: int = 1,
    setting: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    """Deploy a WeChat Mini Program using miniprogram-ci.

    Prerequisites:
    - `miniprogram-ci` npm package installed globally or in project
    - Private key file from WeChat MP admin console
    """
    if not shutil.which("npx"):
        return {"ok": False, "error": "npx not found — install Node.js"}

    if not os.path.exists(private_key_path):
        return {"ok": False, "error": f"Private key not found: {private_key_path}"}

    if not os.path.exists(os.path.join(project_dir, "app.json")):
        return {"ok": False, "error": "Not a miniprogram project (app.json missing)"}

    await emit_event("deploy:start", {
        "platform": "wechat-miniprogram",
        "appId": app_id,
        "version": version,
    })

    upload_settings = {
        "es6": True,
        "es7": True,
        "minify": True,
        "codeProtect": False,
        "minifyJS": True,
        "minifyWXML": True,
        "minifyWXSS": True,
        "autoPrefixWXSS": True,
        **(setting or {}),
    }

    script = f"""
const ci = require('miniprogram-ci');

(async () => {{
    const project = new ci.Project({{
        appid: '{app_id}',
        type: 'miniProgram',
        projectPath: '{project_dir}',
        privateKeyPath: '{private_key_path}',
        ignores: ['node_modules/**/*'],
    }});

    const uploadResult = await ci.upload({{
        project,
        version: '{version}',
        desc: '{description}',
        robot: {robot},
        setting: {json.dumps(upload_settings)},
        onProgressUpdate: console.log,
    }});

    console.log(JSON.stringify({{ ok: true, result: uploadResult }}));
}})().catch(err => {{
    console.error(JSON.stringify({{ ok: false, error: err.message }}));
    process.exit(1);
}});
"""

    script_path = os.path.join(project_dir, "_ci_upload.js")
    with open(script_path, "w") as f:
        f.write(script)

    try:
        proc = await asyncio.create_subprocess_exec(
            "node", script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project_dir,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            await emit_event("deploy:failed", {
                "platform": "wechat-miniprogram",
                "error": stderr_str[:500],
            })
            return {"ok": False, "error": stderr_str[:2000], "stdout": stdout_str[:2000]}

        try:
            result = json.loads(stdout_str.strip().split("\n")[-1])
        except (json.JSONDecodeError, IndexError):
            result = {"raw": stdout_str[:2000]}

        await emit_event("deploy:complete", {
            "platform": "wechat-miniprogram",
            "appId": app_id,
            "version": version,
        })

        return {
            "ok": True,
            "platform": "wechat-miniprogram",
            "appId": app_id,
            "version": version,
            "result": result,
        }

    except asyncio.TimeoutError:
        return {"ok": False, "error": "miniprogram-ci upload timed out (300s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if os.path.exists(script_path):
            os.unlink(script_path)


async def preview_miniprogram(
    *,
    project_dir: str,
    app_id: str,
    private_key_path: str,
    qrcode_output: str = "preview-qr.png",
    robot: int = 1,
) -> Dict[str, Any]:
    """Generate a preview QR code for testing."""
    if not shutil.which("npx"):
        return {"ok": False, "error": "npx not found"}

    qr_path = os.path.join(project_dir, qrcode_output)

    script = f"""
const ci = require('miniprogram-ci');

(async () => {{
    const project = new ci.Project({{
        appid: '{app_id}',
        type: 'miniProgram',
        projectPath: '{project_dir}',
        privateKeyPath: '{private_key_path}',
        ignores: ['node_modules/**/*'],
    }});

    await ci.preview({{
        project,
        desc: 'Preview from Agent Hub',
        robot: {robot},
        qrcodeFormat: 'image',
        qrcodeOutputDest: '{qr_path}',
        onProgressUpdate: console.log,
    }});

    console.log(JSON.stringify({{ ok: true, qrcodePath: '{qr_path}' }}));
}})().catch(err => {{
    console.error(JSON.stringify({{ ok: false, error: err.message }}));
    process.exit(1);
}});
"""

    script_path = os.path.join(project_dir, "_ci_preview.js")
    with open(script_path, "w") as f:
        f.write(script)

    try:
        proc = await asyncio.create_subprocess_exec(
            "node", script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project_dir,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            return {"ok": False, "error": stderr.decode()[:1000]}

        return {
            "ok": True,
            "qrcodePath": qr_path,
            "exists": os.path.exists(qr_path),
        }
    except asyncio.TimeoutError:
        return {"ok": False, "error": "Preview generation timed out"}
    finally:
        if os.path.exists(script_path):
            os.unlink(script_path)
