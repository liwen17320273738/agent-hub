#!/usr/bin/env python3
"""
从 ccMixter 公开 API 拉取带 cantonese 标签、CC 许可的曲目并下载为 MP3。

仅用于 Creative Commons 素材；请勿用于爬取网易云/QQ 音乐等平台的版权歌曲。

用法：
  python3 scripts/fetch_cc_cantonese_bgm.py --list
  python3 scripts/fetch_cc_cantonese_bgm.py --index 0 -o public/beihai-sea/bgm-yue.mp3
  python3 scripts/fetch_cc_cantonese_bgm.py --allow-nc --index 1 -o out.mp3

依赖：Python 3.9+ 标准库（urllib / json），无需 pip。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

CCMIXTER_API = "https://ccmixter.org/api/query"
REFERER = "https://ccmixter.org/"
UA = "Mozilla/5.0 (compatible; agent-hub-cc-fetch/1.0; +https://github.com)"


def api_request(params: dict[str, str]) -> list[dict[str, Any]]:
    url = f"{CCMIXTER_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def pick_tracks(
    rows: list[dict[str, Any]],
    *,
    allow_nc: bool,
    only_by: bool,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        lic = (row.get("license_name") or "").lower()
        if only_by and "noncommercial" in lic:
            continue
        if not allow_nc and "noncommercial" in lic:
            continue
        files = row.get("files") or []
        if not files:
            continue
        u = files[0].get("download_url")
        if not u:
            continue
        out.append(
            {
                "name": row.get("upload_name", "?"),
                "artist": row.get("user_name", "?"),
                "license": row.get("license_name", "?"),
                "url": u,
                "file_page": row.get("file_page_url", ""),
            }
        )
    return out


def download_mp3(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Referer": REFERER},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    dest.write_bytes(data)


def main() -> int:
    p = argparse.ArgumentParser(description="Download CC-licensed Cantonese-tagged audio from ccMixter.")
    p.add_argument("--list", action="store_true", help="只列出候选曲目，不下载")
    p.add_argument("--index", type=int, default=0, help="在过滤后的列表中选第几条（从 0 开始）")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("public/beihai-sea/bgm-yue.mp3"),
        help="输出 MP3 路径",
    )
    p.add_argument(
        "--allow-nc",
        action="store_true",
        help="允许 CC BY-NC 等非商业许可（默认跳过，便于公开站点使用）",
    )
    p.add_argument(
        "--only-by",
        action="store_true",
        help="仅保留名称里含 Attribution 且不含 Noncommercial 的条目（更严）",
    )
    p.add_argument("--limit", type=int, default=25, help="API 返回条数上限")
    args = p.parse_args()

    try:
        rows = api_request({"f": "json", "tags": "cantonese", "limit": str(args.limit)})
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        print("API 请求失败:", e, file=sys.stderr)
        return 1

    if not isinstance(rows, list):
        print("API 返回格式异常", file=sys.stderr)
        return 1

    tracks = pick_tracks(rows, allow_nc=args.allow_nc, only_by=args.only_by)
    if not tracks:
        print("没有符合条件的曲目（可试 --allow-nc 或去掉 --only-by）", file=sys.stderr)
        return 1

    if args.list:
        for i, t in enumerate(tracks):
            print(f"[{i}] {t['name']} — {t['artist']} | {t['license']}")
            print(f"    {t['url']}")
        return 0

    if args.index < 0 or args.index >= len(tracks):
        print(f"index 超出范围 0..{len(tracks) - 1}", file=sys.stderr)
        return 1

    t = tracks[args.index]
    print("下载:", t["name"], "|", t["artist"], "|", t["license"])
    print("来源:", t["file_page"] or t["url"])
    try:
        download_mp3(t["url"], args.output)
    except urllib.error.HTTPError as e:
        print("下载失败 HTTP", e.code, file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print("下载失败:", e, file=sys.stderr)
        return 1

    print("已保存:", args.output.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
