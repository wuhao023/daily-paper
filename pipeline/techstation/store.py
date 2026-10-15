"""data/ 目录下所有 JSON 文件的读写。所有状态都以文件形式提交进 git，不依赖数据库。"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .config import (
    DATA_DIR,
    AGENTS_DIR,
    AGENT_SNAPSHOT_PATH,
    LIBRARY_PATH,
    PAPERS_DIR,
    REPO_SNAPSHOT_PATH,
    REPOS_DIR,
    SEARCH_INDEX_PATH,
    SEEN_PAPERS_PATH,
    THUMBS_DIR,
)

log = logging.getLogger(__name__)


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        log.warning("读取 %s 失败，按空处理: %s", path, exc)
        return default


def write_json(path: Path, obj, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# 个人书库（由网站写入，管道只读）
# ---------------------------------------------------------------------------


def load_library_items() -> list[dict]:
    lib = read_json(LIBRARY_PATH, {"items": []})
    items = lib.get("items", []) if isinstance(lib, dict) else []
    return [it for it in items if it.get("status") in ("liked", "later", "disliked")]


def ensure_library_file() -> None:
    if not LIBRARY_PATH.exists():
        write_json(LIBRARY_PATH, {"updated": now_iso(), "items": []})


# ---------------------------------------------------------------------------
# 论文去重记录
# ---------------------------------------------------------------------------


def load_seen_papers() -> dict[str, str]:
    return read_json(SEEN_PAPERS_PATH, {})


def save_seen_papers(seen: dict[str, str], retention_days: int) -> None:
    cutoff = (date.today() - timedelta(days=retention_days * 2)).isoformat()
    pruned = {k: v for k, v in seen.items() if v >= cutoff}
    write_json(SEEN_PAPERS_PATH, pruned, compact=True)


# ---------------------------------------------------------------------------
# GitHub star 快照（用于计算增长速度）
# ---------------------------------------------------------------------------


def load_repo_snapshot(kind: str = "repos") -> dict[str, dict]:
    return read_json(AGENT_SNAPSHOT_PATH if kind == "agents" else REPO_SNAPSHOT_PATH, {})


def save_repo_snapshot(snapshot: dict[str, dict], retention_days: int, kind: str = "repos") -> None:
    cutoff = (date.today() - timedelta(days=retention_days)).isoformat()
    pruned = {k: v for k, v in snapshot.items() if v.get("date", "") >= cutoff}
    write_json(AGENT_SNAPSHOT_PATH if kind == "agents" else REPO_SNAPSHOT_PATH, pruned, compact=True)


# ---------------------------------------------------------------------------
# 每日文件
# ---------------------------------------------------------------------------


def write_daily(kind: str, day: str, items: list[dict], meta: dict) -> Path:
    directory = {"papers": PAPERS_DIR, "repos": REPOS_DIR, "agents": AGENTS_DIR}[kind]
    path = directory / f"{day}.json"
    write_json(path, {"date": day, "generated_at": now_iso(), **meta, "items": items})
    return path


def read_daily(kind: str, day: str) -> dict:
    directory = {"papers": PAPERS_DIR, "repos": REPOS_DIR, "agents": AGENTS_DIR}[kind]
    return read_json(directory / f"{day}.json", {})


def list_daily_files(kind: str) -> list[Path]:
    directory = {"papers": PAPERS_DIR, "repos": REPOS_DIR, "agents": AGENTS_DIR}[kind]
    if not directory.exists():
        return []
    return sorted(directory.glob("????-??-??.json"))


def prune_daily_files(kind: str, retention_days: int) -> None:
    cutoff = (date.today() - timedelta(days=retention_days)).isoformat()
    for path in list_daily_files(kind):
        if path.stem < cutoff:
            log.info("删除过期文件 %s", path.name)
            path.unlink()


def prune_thumbnails() -> None:
    """删除不再被任何每日文件 / 学者追踪引用的 PDF 缩略图，控制仓库体积。"""
    if not THUMBS_DIR.exists():
        return
    referenced: set[str] = set()
    for path in list_daily_files("papers"):
        for p in read_json(path, {}).get("items", []):
            if p.get("figure_source") == "pdf":
                referenced.add(p["id"])
    for lab in read_json(DATA_DIR / "labs.json", {}).get("labs", []):
        for r in lab.get("researchers", []):
            for p in r.get("papers", []):
                if p.get("figure_source") == "pdf":
                    referenced.add(p["id"])
    removed = 0
    for f in THUMBS_DIR.glob("*.jpg"):
        if f.stem not in referenced:
            f.unlink()
            removed += 1
    if removed:
        log.info("清理了 %d 张不再引用的缩略图", removed)


# ---------------------------------------------------------------------------
# 搜索索引（网站端用 MiniSearch 加载）
# ---------------------------------------------------------------------------


def _compact_paper(p: dict, day: str) -> dict:
    return {
        "t": "paper",
        "id": p["id"],
        "title": p["title"],
        "authors": ", ".join(p.get("authors", [])[:6]) + (" 等" if len(p.get("authors", [])) > 6 else ""),
        "text": (p.get("abstract") or "")[:700],
        "tags": p.get("categories", []),
        "url": p["url"],
        "date": p.get("published", "")[:10],
        "day": day,
        "score": p.get("score", 0),
        "img": p.get("figure_url"),
        "kw": p.get("matched_keywords") or [],
        "tracked": p.get("tracked_authors") or [],
    }


def _compact_repo(r: dict, day: str) -> dict:
    return {
        "t": "repo",
        "id": r["id"],
        "title": r["full_name"],
        "authors": r.get("language") or "",
        "text": (r.get("description") or "")[:500],
        "tags": r.get("topics", [])[:10],
        "url": r["url"],
        "date": r.get("created_at", "")[:10],
        "day": day,
        "score": r.get("score", 0),
        "stars": r.get("stars", 0),
        "img": r.get("image_url") or r.get("og_image"),
        "kw": r.get("matched_keywords") or [],
    }


def rebuild_search_index(retention_days: int) -> None:
    """从所有每日文件重建索引；同一 id 只保留最新一次出现。"""
    cutoff = (date.today() - timedelta(days=retention_days)).isoformat()
    papers: dict[str, dict] = {}
    repos: dict[str, dict] = {}

    for path in list_daily_files("papers"):
        if path.stem < cutoff:
            continue
        for p in read_json(path, {}).get("items", []):
            papers[p["id"]] = _compact_paper(p, path.stem)

    for path in sorted(list_daily_files("repos") + list_daily_files("agents"), key=lambda p: p.stem):
        if path.stem < cutoff:
            continue
        for r in read_json(path, {}).get("items", []):
            repos[r["id"]] = _compact_repo(r, path.stem)

    index = {
        "updated": now_iso(),
        "items": sorted(papers.values(), key=lambda d: d["day"], reverse=True)
        + sorted(repos.values(), key=lambda d: d["day"], reverse=True),
    }
    write_json(SEARCH_INDEX_PATH, index, compact=True)
    size_kb = SEARCH_INDEX_PATH.stat().st_size / 1024
    log.info("搜索索引：%d 篇论文，%d 个项目，%.0f KB", len(papers), len(repos), size_kb)
