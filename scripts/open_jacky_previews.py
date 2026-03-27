#!/usr/bin/env python3
"""
在默认浏览器中打开 public/jacky-cheung-previews.html。

该页通过 iTunes Search API 动态加载每首歌约 30 秒的官方试听（非整首、无版权下载）。

用法：
  python3 scripts/open_jacky_previews.py
"""

from __future__ import annotations

import webbrowser
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    html = root / "public" / "jacky-cheung-previews.html"
    if not html.is_file():
        raise SystemExit(f"找不到页面: {html}")
    url = html.as_uri()
    webbrowser.open(url)
    print("已尝试打开:", url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
