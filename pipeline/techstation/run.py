"""管道入口：抓取 -> 打分 -> 配图 -> 学者追踪 -> 写文件 -> 重建搜索索引。

用法：
    uv run techstation                 # 完整运行
    uv run techstation --skip-github   # 只跑 arXiv
    uv run techstation --no-embedding  # 不加载模型，只用关键词（调试用）
    uv run techstation --quick         # 快速模式（网站「刷新推荐」用）：跳过学者追踪
    uv run techstation --skip-media --skip-labs   # 最快的调试模式
"""

from __future__ import annotations

import argparse
import logging
import math
import re
from datetime import date, datetime, timedelta, timezone

import numpy as np

from . import arxiv, github, labs, media, store
from .config import Config, REPO_ROOT
from .scoring import Embedder, KeywordScorer, build_profile, score_items

log = logging.getLogger("techstation")


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="每日论文 / 项目推荐管道")
    ap.add_argument("--date", help="覆盖今天的日期（YYYY-MM-DD），默认取 UTC 今天")
    ap.add_argument("--skip-arxiv", action="store_true")
    ap.add_argument("--skip-github", action="store_true", help="跳过机器人与 Agent 项目")
    ap.add_argument("--agents-only", action="store_true", help="只更新 Agent 项目及搜索索引")
    ap.add_argument("--skip-labs", action="store_true", help="不更新学者追踪")
    ap.add_argument("--skip-media", action="store_true", help="不抓配图（省时间）")
    ap.add_argument("--quick", action="store_true", help="快速模式：只更新论文与项目推荐，跳过学者追踪（约省 3 分钟）")
    ap.add_argument("--no-embedding", action="store_true", help="不加载 embedding 模型")
    ap.add_argument("--keep-seen", action="store_true", help="不排除以前推荐过的论文（调试用）")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args()


def _boost_tracked(items: list[dict], boost: float) -> None:
    """命中追踪学者的论文加分并补充解释。"""
    if boost <= 0:
        return
    for p in items:
        if p.get("tracked_authors"):
            p["score"] = round(p["score"] + boost, 4)
            names = "、".join(p["tracked_authors"][:2])
            p["why"] = f"追踪学者：{names}" + (f"；{p['why']}" if p.get("why") else "")
    items.sort(key=lambda d: d["score"], reverse=True)


def run_papers(cfg: Config, day: str, profile, embedder, kw, labs_profile: dict, args) -> int:
    papers = arxiv.fetch_recent(cfg.arxiv_categories, cfg.arxiv_days_back, cfg.arxiv_max_results)
    seen = store.load_seen_papers()
    # 排除以前推荐过的；但「今天」已经推荐过的要保留，这样同一天重跑（手动刷新）会合并而不是覆盖
    fresh = [p.to_dict() for p in papers if args.keep_seen or seen.get(p.id) in (None, day)]
    log.info("排除已推荐过的论文后剩余 %d 篇", len(fresh))

    ranked = score_items(
        cfg,
        fresh,
        text_fn=lambda p: f"{p['title']}. {p['abstract']}",
        title_fn=lambda p: p["title"],
        profile=profile,
        embedder=embedder,
        kw_scorer=kw,
    )
    hits = labs.tag_tracked_authors(ranked, labs_profile)
    if hits:
        log.info("%d 篇论文命中追踪学者", hits)
    _boost_tracked(ranked, float(labs_profile.get("boost", 0)))

    top = ranked[: cfg.top_k_papers]
    for rank, p in enumerate(top, start=1):
        p["rank"] = rank

    # 配图：优先复用今天已有文件里的结果，避免重复请求 arxiv.org
    if not args.skip_media:
        existing = {p["id"]: p for p in store.read_daily("papers", day).get("items", [])}
        todo = []
        for p in top:
            old = existing.get(p["id"])
            if old and old.get("figure_url"):
                for k in ("figure_url", "figure_caption", "figure_source", "video_url", "links"):
                    p[k] = old.get(k)
            else:
                todo.append(p)
        media.enrich_papers(todo)

    store.write_daily(
        "papers",
        day,
        top,
        {"total_fetched": len(papers), "total_new": len(fresh), "categories": cfg.arxiv_categories},
    )
    for p in fresh:
        seen[p["id"]] = day
    store.save_seen_papers(seen, cfg.retention_days)
    return len(top)


def run_repos(cfg: Config, day: str, profile, embedder, kw, args, kind: str = "repos") -> int:
    repos = [r.to_dict() for r in github.fetch_repos(cfg.github_topics, cfg.github_queries, cfg.github_min_stars, cfg.github_days_back)]
    if kind == "agents":
        # 仅保留有明确许可证的实现，降低资源清单和普通软件 agent 的干扰。
        agent_pattern = re.compile(r"\b(?:agents?|agentic|multiagent)\b", re.I)
        repos = [
            r for r in repos
            if r.get("license") not in (None, "", "NOASSERTION", "OTHER")
            and agent_pattern.search(f"{r['name']} {r['description']} {' '.join(r['topics'])}")
            and not r['name'].lower().startswith("awesome-")
        ]
        if not repos:
            log.warning("Agent 候选为空，保留已有推荐和 Star 快照")
            return 0
    snapshot = store.load_repo_snapshot(kind)
    now = datetime.now(timezone.utc)
    new_cutoff = now - timedelta(days=cfg.github_days_back)

    for r in repos:
        prev = snapshot.get(r["id"])
        # 同一天重跑时快照已是今天的值，增量会变 0；此时沿用快照里记录的上一次增量
        if prev and prev.get("date") == day and prev.get("delta") is not None:
            r["stars_delta"] = prev["delta"]
        else:
            r["stars_delta"] = (r["stars"] - prev["stars"]) if prev else None
        r["first_seen"] = prev["first_seen"] if prev and "first_seen" in prev else day
        created = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) if r["created_at"] else now
        r["is_new"] = created >= new_cutoff

    ranked = score_items(
        cfg,
        repos,
        text_fn=lambda r: f"{r['full_name']}: {r['description']} Topics: {', '.join(r['topics'])}",
        title_fn=lambda r: f"{r['name']} {r['description']}",
        profile=profile,
        embedder=embedder,
        kw_scorer=kw,
    )

    # 融合热度：新项目看总 star，老项目看 star 增量；再加一点活跃度
    if ranked:
        pop = np.array(
            [
                math.log1p(max(r["stars_delta"], 0)) if r["stars_delta"] is not None else math.log1p(r["stars"]) * 0.6
                for r in ranked
            ],
            dtype=np.float32,
        )
        pop = (pop - pop.min()) / (pop.max() - pop.min() + 1e-9)
        for r, p in zip(ranked, pop):
            pushed = datetime.fromisoformat(r["pushed_at"].replace("Z", "+00:00")) if r["pushed_at"] else now
            recency = max(0.0, 1 - (now - pushed).days / max(cfg.github_days_back, 1))
            r["score_relevance"] = r["score"]
            r["score"] = round(0.65 * r["score"] + 0.25 * float(p) + 0.10 * recency, 4)
        ranked.sort(key=lambda r: r["score"], reverse=True)

    top = ranked[: cfg.top_k_repos]
    for rank, r in enumerate(top, start=1):
        r["rank"] = rank

    if not args.skip_media:
        existing = {r["id"]: r for r in store.read_daily(kind, day).get("items", [])}
        todo = []
        for r in top:
            old = existing.get(r["id"])
            if old and "og_image" in old:
                for k in ("og_image", "image_url", "video_url"):
                    r[k] = old.get(k)
            else:
                todo.append(r)
        media.enrich_repos(todo)

    store.write_daily(kind, day, top, {"total_fetched": len(repos), "topics": cfg.github_topics, "new_days": cfg.github_days_back})

    for r in repos:
        prev = snapshot.get(r["id"])
        if prev and prev.get("date") != day:
            delta = r["stars"] - prev["stars"]
        else:
            delta = (prev or {}).get("delta")
        snapshot[r["id"]] = {"stars": r["stars"], "date": day, "first_seen": r["first_seen"], "delta": delta}
    store.save_repo_snapshot(snapshot, cfg.retention_days, kind)
    return len(top)


def main() -> None:
    args = _parse_args()
    if args.agents_only and args.skip_github:
        raise SystemExit("--agents-only 不能与 --skip-github 同时使用")
    if args.agents_only:
        args.skip_arxiv = args.skip_labs = True
    if args.quick:
        args.skip_labs = True
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "huggingface_hub", "urllib3", "fastembed"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    cfg = Config.load()
    labs_profile = labs.load_labs_profile()
    day = args.date or date.today().isoformat()
    log.info("开始运行，日期 %s%s", day, "（快速模式）" if args.quick else "")

    store.ensure_library_file()
    library_items = store.load_library_items()
    embedder = None if args.no_embedding else Embedder(cfg.embedding_model)
    profile = build_profile(cfg, library_items, embedder)
    kw = KeywordScorer(cfg.boost_keywords, cfg.mute_keywords)

    if not args.skip_arxiv:
        n = run_papers(cfg, day, profile, embedder, kw, labs_profile, args)
        log.info("论文推荐写入 %d 篇", n)
    if not args.skip_github:
        if not args.agents_only:
            n = run_repos(cfg, day, profile, embedder, kw, args)
            log.info("项目推荐写入 %d 个", n)
        agent_cfg = Config.load(REPO_ROOT / "profile" / "agents.yaml")
        agent_cfg.retention_days = cfg.retention_days
        # 独立兴趣画像，避免机器人收藏影响 Agent 排名。
        agent_profile = build_profile(agent_cfg, [], embedder)
        agent_kw = KeywordScorer(agent_cfg.boost_keywords, agent_cfg.mute_keywords)
        n = run_repos(agent_cfg, day, agent_profile, embedder, agent_kw, args, kind="agents")
        log.info("Agent 项目推荐写入 %d 个", n)
    if not args.skip_labs and labs_profile["labs"]:
        labs.run_labs(labs_profile, day, fetch_media=not args.skip_media)

    if not args.agents_only:
        store.prune_daily_files("papers", cfg.retention_days)
        store.prune_daily_files("repos", cfg.retention_days)
        store.prune_thumbnails()
    if not args.skip_github:
        store.prune_daily_files("agents", cfg.retention_days)
    store.rebuild_search_index(cfg.retention_days)
    log.info("完成")


if __name__ == "__main__":
    main()
