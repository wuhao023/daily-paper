"""读取 profile/interests.yaml 与路径约定。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# 仓库根目录 = pipeline/ 的上一级
REPO_ROOT = Path(os.environ.get("TECHSTATION_ROOT", Path(__file__).resolve().parents[2]))
DATA_DIR = REPO_ROOT / "data"
PAPERS_DIR = DATA_DIR / "papers"
REPOS_DIR = DATA_DIR / "repos"
AGENTS_DIR = DATA_DIR / "agents"
AGENT_SNAPSHOT_PATH = DATA_DIR / "agents-seen.json"
PROFILE_PATH = REPO_ROOT / "profile" / "interests.yaml"
LIBRARY_PATH = DATA_DIR / "library.json"
SEEN_PAPERS_PATH = DATA_DIR / "seen-papers.json"
REPO_SNAPSHOT_PATH = DATA_DIR / "repos-seen.json"
SEARCH_INDEX_PATH = DATA_DIR / "search-index.json"
THUMBS_DIR = DATA_DIR / "thumbs"  # 没有 HTML 配图时，用 PDF 首页渲染的缩略图
CACHE_DIR = REPO_ROOT / "pipeline" / ".cache"


@dataclass
class Config:
    arxiv_categories: list[str]
    arxiv_days_back: int
    arxiv_max_results: int
    interests: list[str]
    boost_keywords: list[str]
    mute_keywords: list[str]
    github_topics: list[str]
    github_queries: list[str]
    github_min_stars: int
    github_days_back: int
    embedding_model: str
    top_k_papers: int
    top_k_repos: int
    weight_embedding: float
    weight_keyword: float
    retention_days: int
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = PROFILE_PATH) -> "Config":
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        arxiv = raw.get("arxiv", {})
        kw = raw.get("keywords", {})
        gh = raw.get("github", {})
        sc = raw.get("scoring", {})
        weights = sc.get("weights", {})
        return cls(
            arxiv_categories=list(arxiv.get("categories", ["cs.RO"])),
            arxiv_days_back=int(arxiv.get("days_back", 7)),
            arxiv_max_results=int(arxiv.get("max_results_per_category", 400)),
            interests=[str(s) for s in raw.get("interests", [])],
            boost_keywords=[str(s) for s in kw.get("boost", [])],
            mute_keywords=[str(s) for s in kw.get("mute", [])],
            github_topics=[str(s) for s in gh.get("topics", [])],
            github_queries=[str(s) for s in gh.get("queries", [])],
            github_min_stars=int(gh.get("min_stars", 10)),
            github_days_back=int(gh.get("days_back", 30)),
            embedding_model=str(sc.get("embedding_model", "BAAI/bge-small-en-v1.5")),
            top_k_papers=int(sc.get("top_k_papers", 50)),
            top_k_repos=int(sc.get("top_k_repos", 30)),
            weight_embedding=float(weights.get("embedding", 0.7)),
            weight_keyword=float(weights.get("keyword", 0.3)),
            retention_days=int(raw.get("retention_days", 120)),
            raw=raw,
        )
