#!/usr/bin/env python3
"""
从 MusicBrainz 公开 API 查询张学友指定曲目的录音元数据（标题、专辑、发行日期、MBID）。

数据源：https://musicbrainz.org — 需遵守 1 请求/秒，使用带联系方式的 User-Agent。

歌名说明：用户常用简体「应该不应该」在库中常登记为「該不該」等，脚本会对每个意图尝试多个别名。

依赖：Python 3.9+ 标准库（urllib / json / time），无需 pip。

用法：
  python3 scripts/fetch_jacky_cheung_tracks.py
  python3 scripts/fetch_jacky_cheung_tracks.py --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# 張學友 / Jacky Cheung — https://musicbrainz.org/artist/a2cab261-63cc-4ccf-8023-6b6e8588bb62
JACKY_ARID = "a2cab261-63cc-4ccf-8023-6b6e8588bb62"
UA = "agent-hub-jacky-fetch/1.0 (+https://github.com)"
BASE = "https://musicbrainz.org/ws/2"

# (展示用标签, MusicBrainz 上可能出现的录音标题，按优先顺序)
DEFAULT_INTENTS: list[tuple[str, list[str]]] = [
    ("应该不应该", ["應不應該", "該不該", "应该不应该", "该该不该"]),
    ("离开以后", ["離開以後", "离开以后"]),
    ("讲你知", ["講你知", "讲你知"]),
]


def _request_curl(url: str) -> dict[str, Any]:
    """部分 macOS 自带 Python 对 musicbrainz.org TLS 握手会失败，curl 通常可用。"""
    cmd = [
        "curl",
        "-sS",
        "-f",
        "--max-time",
        "45",
        "-H",
        f"User-Agent: {UA}",
        "-H",
        "Accept: application/json",
        url,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"curl failed ({p.returncode}): {p.stderr.strip() or p.stdout[:300]}")
    return json.loads(p.stdout)


def _request(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"HTTP {e.code}: {body[:500]}") from e
    except (urllib.error.URLError, OSError):
        return _request_curl(url)


def search_recordings(query: str) -> list[dict[str, Any]]:
    qs = urllib.parse.urlencode({"query": query, "fmt": "json", "limit": "15"})
    data = _request(f"{BASE}/recording?{qs}")
    return list(data.get("recordings") or [])


def recording_detail(mbid: str) -> dict[str, Any]:
    qs = urllib.parse.urlencode({"fmt": "json", "inc": "artist-credits+releases"})
    return _request(f"{BASE}/recording/{mbid}?{qs}")


def pick_recording(intent_label: str, title_candidates: list[str]) -> dict[str, Any] | None:
    """在张学友录音中，优先匹配标题与候选列表一致的条目。"""
    seen: set[str] = set()
    for title in title_candidates:
        time.sleep(1.05)
        # 短语用引号减少误匹配（如「應該」撞到「我應該」）
        q = f'arid:{JACKY_ARID} AND recording:"{title}"'
        recs = search_recordings(q)
        for r in recs:
            rid = r.get("id")
            if not rid or rid in seen:
                continue
            seen.add(rid)
            if r.get("title") == title:
                return r
        time.sleep(1.05)
        q2 = f"arid:{JACKY_ARID} AND recording:{title}"
        for r in search_recordings(q2):
            rid = r.get("id")
            if not rid or rid in seen:
                continue
            if r.get("title") in title_candidates:
                return r
    return None


def summarize(detail: dict[str, Any]) -> dict[str, Any]:
    credits = detail.get("artist-credit") or []
    artists = [c.get("name") for c in credits if isinstance(c, dict) and c.get("name")]
    rels = detail.get("releases") or []
    albums: list[dict[str, Any]] = []
    for rel in rels[:12]:
        if not isinstance(rel, dict):
            continue
        albums.append(
            {
                "title": rel.get("title"),
                "date": rel.get("date"),
                "status": rel.get("status"),
                "country": rel.get("country"),
            }
        )
    return {
        "recording_mbid": detail.get("id"),
        "title": detail.get("title"),
        "length_ms": detail.get("length"),
        "artists": artists,
        "releases_sample": albums,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Query Jacky Cheung tracks on MusicBrainz.")
    ap.add_argument("--json", action="store_true", help="Print one JSON object to stdout.")
    args = ap.parse_args()
    out: list[dict[str, Any]] = []

    for user_label, candidates in DEFAULT_INTENTS:
        time.sleep(1.05)
        rec = pick_recording(user_label, candidates)
        if not rec:
            out.append({"user_label": user_label, "error": "no matching recording found"})
            continue
        time.sleep(1.05)
        detail = recording_detail(rec["id"])
        row = {"user_label": user_label, **summarize(detail)}
        # 若用户说的歌名与 MB 标题不同，标出来
        mb_title = row.get("title")
        if mb_title and mb_title not in candidates and user_label not in (mb_title,):
            row["note"] = f"库中标题为「{mb_title}」，与常用说法可能不同"
        out.append(row)

    if args.json:
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    for row in out:
        print("=" * 48)
        print("你想查的:", row.get("user_label"))
        if "error" in row:
            print("  ", row["error"])
            continue
        print("  录音标题:", row.get("title"))
        print("  MBID:", row.get("recording_mbid"))
        print("  艺人:", " / ".join(row.get("artists") or []))
        if row.get("note"):
            print("  说明:", row["note"])
        rels = row.get("releases_sample") or []
        if rels:
            print("  专辑（节选）:")
            for a in rels[:5]:
                print(f"    - {a.get('title')} ({a.get('date') or '?'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
