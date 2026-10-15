/** 构建时读取仓库根目录 data/ 下的 JSON 文件（服务端使用）。 */
import { resolveMedia } from './base';
import type { CardItem, DailyFile, Lab, LabPaper, LabsFile, Paper, Repo } from './types';

const paperFiles = import.meta.glob<DailyFile<Paper>>('../../../data/papers/*.json', {
  eager: true,
  import: 'default',
});
const repoFiles = import.meta.glob<DailyFile<Repo>>('../../../data/repos/*.json', {
  eager: true,
  import: 'default',
});
const agentFiles = import.meta.glob<DailyFile<Repo>>('../../../data/agents/*.json', { eager: true, import: 'default' });
const labsFiles = import.meta.glob<LabsFile>('../../../data/labs.json', { eager: true, import: 'default' });

function byDateDesc<T extends { date: string }>(files: Record<string, T>): T[] {
  return Object.values(files).sort((a, b) => (a.date < b.date ? 1 : -1));
}

export const paperDays: DailyFile<Paper>[] = byDateDesc(paperFiles);
export const repoDays: DailyFile<Repo>[] = byDateDesc(repoFiles);
export const agentDays: DailyFile<Repo>[] = byDateDesc(agentFiles);
export const latestAgents = agentDays.find((d) => d.items.length > 0);
export function agentsOn(date: string): DailyFile<Repo> | undefined {
  return agentDays.find((d) => d.date === date);
}
export const labsData: LabsFile | undefined = Object.values(labsFiles)[0];

/* ---------- 学者追踪：嵌套页面用的 slug 工具 ---------- */
export function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
export function labSlug(lab: Lab): string {
  return lab.slug || slugify(lab.short) || slugify(lab.name) || 'lab';
}
export function researcherSlug(name: string): string {
  return slugify(name) || encodeURIComponent(name);
}
export const labs: Lab[] = labsData?.labs ?? [];
export function findLab(slug: string): Lab | undefined {
  return labs.find((l) => labSlug(l) === slug);
}
/** 一位学者最近的论文按日期倒序 */
export function sortedPapers(ps: LabPaper[]): LabPaper[] {
  return [...ps].sort((a, b) => (a.published < b.published ? 1 : -1));
}

export const latestPapers = paperDays[0];
export const latestRepos = repoDays[0];

/** 所有出现过的日期（论文或项目任一有数据） */
export const allDates: string[] = Array.from(
  new Set([...paperDays.map((d) => d.date), ...repoDays.map((d) => d.date), ...agentDays.map((d) => d.date)]),
).sort((a, b) => (a < b ? 1 : -1));

export function papersOn(date: string): DailyFile<Paper> | undefined {
  return paperDays.find((d) => d.date === date);
}
export function reposOn(date: string): DailyFile<Repo> | undefined {
  return repoDays.find((d) => d.date === date);
}

/** 把学者追踪里的论文补成完整 Paper（没有分数等字段） */
function labPaperToPaper(p: LabPaper, researcher: string): Paper {
  return {
    ...p,
    primary_category: p.categories[0] ?? '',
    updated: p.published,
    score: undefined as unknown as number,
    score_embedding: null,
    score_keyword: 0,
    matched_keywords: [],
    muted_keywords: [],
    why: '',
    rank: 0,
    tracked_authors: [researcher],
  };
}

/**
 * 所有需要详情页的论文（去重）。day 为它出现在每日推荐的日期；
 * 只出现在学者追踪里的论文 day 为 null。
 */
export function allPapers(): { paper: Paper; day: string | null }[] {
  const seen = new Map<string, { paper: Paper; day: string | null }>();
  for (const d of paperDays) for (const p of d.items) if (!seen.has(p.id)) seen.set(p.id, { paper: p, day: d.date });
  for (const lab of labsData?.labs ?? [])
    for (const r of lab.researchers)
      for (const p of r.papers) {
        const cur = seen.get(p.id);
        if (!cur) seen.set(p.id, { paper: labPaperToPaper(p, r.name), day: null });
        else if (cur.paper.tracked_authors && !cur.paper.tracked_authors.includes(r.name)) cur.paper.tracked_authors.push(r.name);
      }
  return Array.from(seen.values());
}
export function allRepos(): { repo: Repo; day: string }[] {
  const seen = new Map<string, { repo: Repo; day: string }>();
  for (const d of [...agentDays, ...repoDays].sort((a, b) => b.date.localeCompare(a.date))) for (const r of d.items) if (!seen.has(r.id)) seen.set(r.id, { repo: r, day: d.date });
  return Array.from(seen.values());
}

export function authorsLine(authors: string[], max = 6): string {
  return authors.slice(0, max).join(', ') + (authors.length > max ? ' 等' : '');
}

export function paperToCard(p: Paper): CardItem {
  const links: { label: string; url: string }[] = [];
  if (p.links?.project) links.push({ label: '项目主页', url: p.links.project });
  if (p.links?.code) links.push({ label: '代码', url: p.links.code });
  return {
    type: 'paper',
    id: p.id,
    title: p.title,
    url: p.url,
    subtitle: authorsLine(p.authors),
    text: p.abstract,
    tags: p.categories,
    date: p.published.slice(0, 10),
    score: typeof p.score === 'number' ? p.score : undefined,
    why: p.why,
    keywords: p.matched_keywords,
    pdf: p.pdf_url,
    image: resolveMedia(p.figure_url),
    imageCaption: p.figure_caption ?? '',
    video: p.video_url ?? null,
    links,
    badges: (p.tracked_authors ?? []).map((n) => `追踪学者 · ${n}`),
  };
}

export function labPaperToCard(p: LabPaper, researcher: string): CardItem {
  const links: { label: string; url: string }[] = [];
  if (p.links?.project) links.push({ label: '项目主页', url: p.links.project });
  if (p.links?.code) links.push({ label: '代码', url: p.links.code });
  return {
    type: 'paper',
    id: p.id,
    title: p.title,
    url: p.url,
    subtitle: authorsLine(p.authors, 8),
    text: p.abstract,
    tags: p.categories,
    date: p.published.slice(0, 10),
    pdf: p.pdf_url,
    image: resolveMedia(p.figure_url),
    imageCaption: p.figure_caption ?? '',
    video: p.video_url ?? null,
    links,
    badges: [`追踪学者 · ${researcher}`],
  };
}

export function repoToCard(r: Repo): CardItem {
  const links: { label: string; url: string }[] = [];
  if (r.homepage) links.push({ label: '主页', url: r.homepage });
  return {
    type: 'repo',
    id: r.id,
    title: r.full_name,
    url: r.url,
    subtitle: r.language || '',
    text: r.description,
    tags: r.topics.slice(0, 10),
    date: r.created_at.slice(0, 10),
    score: r.score,
    why: r.why,
    keywords: r.matched_keywords,
    stars: r.stars,
    starsDelta: r.stars_delta,
    isNew: r.is_new,
    image: r.image_url || r.og_image || `https://opengraph.githubassets.com/1/${r.full_name}`,
    video: r.video_url ?? null,
    links,
  };
}
