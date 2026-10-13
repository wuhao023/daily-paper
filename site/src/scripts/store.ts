/**
 * 个人书库的本地存储（localStorage）+ 可选的 GitHub 同步。
 *
 * - 所有状态先写本地，立即生效，不依赖网络。
 * - 若在「设置」里配置了 GitHub token，会把 data/library.json 推回仓库，
 *   这样其他设备能看到，下一次每日管道也会把点赞/不感兴趣当作反馈。
 * - 合并规则：按 id 合并，updated_at 新的一方胜出；删除用 status='removed' 墓碑表示。
 */
import type { CardItem, LibraryFile, LibraryItem, LibraryStatus } from '../lib/types';
import { b64encode, b64decode } from '../lib/base64';

const LIB_KEY = 'ts:library:v1';
const SYNC_KEY = 'ts:sync:v1';
const PULL_STAMP_KEY = 'ts:sync:lastPull';

export interface SyncSettings {
  token: string;
  repo: string; // owner/name
  branch: string;
  path: string; // data/library.json
}

type Listener = (items: LibraryItem[]) => void;
const listeners = new Set<Listener>();

// ---------------------------------------------------------------------------
// 本地读写
// ---------------------------------------------------------------------------

export function loadLibrary(): LibraryItem[] {
  try {
    const raw = localStorage.getItem(LIB_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as LibraryFile | LibraryItem[];
    return Array.isArray(parsed) ? parsed : parsed.items ?? [];
  } catch {
    return [];
  }
}

function saveLibrary(items: LibraryItem[]): void {
  const file: LibraryFile = { updated: new Date().toISOString(), items };
  localStorage.setItem(LIB_KEY, JSON.stringify(file));
  listeners.forEach((fn) => fn(items));
  window.dispatchEvent(new CustomEvent('ts:library-changed'));
}

export function onLibraryChange(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function getItem(id: string): LibraryItem | undefined {
  return loadLibrary().find((it) => it.id === id && it.status !== 'removed');
}

function deriveStatus(it: Pick<LibraryItem, 'liked' | 'later' | 'disliked'>): LibraryStatus {
  if (it.disliked) return 'disliked';
  if (it.liked) return 'liked';
  if (it.later) return 'later';
  return 'removed';
}

/** 切换某个标记（liked / later / disliked），返回更新后的条目 */
export function toggle(card: CardItem, flag: 'liked' | 'later' | 'disliked'): LibraryItem {
  const items = loadLibrary();
  const now = new Date().toISOString();
  let it = items.find((x) => x.id === card.id);
  if (!it) {
    it = { ...card, liked: false, later: false, disliked: false, status: 'removed', added_at: now, updated_at: now };
    items.push(it);
  } else {
    // 用最新卡片信息刷新元数据（比如分数、摘要）
    Object.assign(it, card);
  }
  it[flag] = !it[flag];
  // 点赞和不感兴趣互斥
  if (flag === 'liked' && it.liked) it.disliked = false;
  if (flag === 'disliked' && it.disliked) it.liked = false;
  it.status = deriveStatus(it);
  it.updated_at = now;
  saveLibrary(items);
  schedulePush();
  return it;
}

export function removeItem(id: string): void {
  const items = loadLibrary();
  const it = items.find((x) => x.id === id);
  if (!it) return;
  it.liked = it.later = it.disliked = false;
  it.status = 'removed';
  it.updated_at = new Date().toISOString();
  saveLibrary(items);
  schedulePush();
}

export function activeItems(): LibraryItem[] {
  return loadLibrary()
    .filter((it) => it.status !== 'removed')
    .sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
}

/** 合并两份列表，updated_at 新者胜。 */
export function merge(a: LibraryItem[], b: LibraryItem[]): LibraryItem[] {
  const map = new Map<string, LibraryItem>();
  for (const it of [...a, ...b]) {
    const prev = map.get(it.id);
    if (!prev || (it.updated_at ?? '') > (prev.updated_at ?? '')) map.set(it.id, it);
  }
  return Array.from(map.values());
}

export function importItems(incoming: LibraryItem[]): number {
  const before = loadLibrary();
  const merged = merge(before, incoming);
  saveLibrary(merged);
  return merged.length - before.length;
}

export function exportFile(): LibraryFile {
  return { updated: new Date().toISOString(), items: loadLibrary() };
}

// ---------------------------------------------------------------------------
// GitHub 同步
// ---------------------------------------------------------------------------

export function loadSyncSettings(): SyncSettings {
  const defaults: SyncSettings = {
    token: '',
    repo: import.meta.env.PUBLIC_REPO || '',
    branch: 'main',
    path: 'data/library.json',
  };
  try {
    const raw = localStorage.getItem(SYNC_KEY);
    return raw ? { ...defaults, ...(JSON.parse(raw) as Partial<SyncSettings>) } : defaults;
  } catch {
    return defaults;
  }
}

export function saveSyncSettings(s: SyncSettings): void {
  localStorage.setItem(SYNC_KEY, JSON.stringify(s));
}

export function syncEnabled(): boolean {
  const s = loadSyncSettings();
  return Boolean(s.token && s.repo);
}

function contentsUrl(s: SyncSettings): string {
  return `https://api.github.com/repos/${s.repo}/contents/${s.path}`;
}

function headers(s: SyncSettings): HeadersInit {
  return {
    Authorization: `Bearer ${s.token}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  };
}

async function fetchRemote(s: SyncSettings): Promise<{ items: LibraryItem[]; sha: string | null }> {
  const res = await fetch(`${contentsUrl(s)}?ref=${encodeURIComponent(s.branch)}`, { headers: headers(s) });
  if (res.status === 404) return { items: [], sha: null };
  if (!res.ok) throw new Error(`GitHub 读取失败 ${res.status}: ${await res.text()}`);
  const json = (await res.json()) as { content: string; sha: string };
  const file = JSON.parse(b64decode(json.content)) as LibraryFile;
  return { items: file.items ?? [], sha: json.sha };
}

export interface SyncResult {
  pulled: number;
  pushed: boolean;
  total: number;
}

/** 拉取远端 -> 合并 -> 如有差异则推送。 */
export async function syncNow(): Promise<SyncResult> {
  const s = loadSyncSettings();
  if (!s.token || !s.repo) throw new Error('未配置 GitHub token 或仓库');

  const local = loadLibrary();
  const { items: remote, sha } = await fetchRemote(s);
  const merged = merge(local, remote);
  saveLibrary(merged);
  sessionStorage.setItem(PULL_STAMP_KEY, String(Date.now()));

  const remoteJson = JSON.stringify(sortForFile(remote));
  const mergedJson = JSON.stringify(sortForFile(merged));
  let pushed = false;
  if (remoteJson !== mergedJson) {
    const file: LibraryFile = { updated: new Date().toISOString(), items: sortForFile(merged) };
    const body: Record<string, string> = {
      message: `library: 同步 ${file.items.filter((i) => i.status !== 'removed').length} 条收藏`,
      content: b64encode(JSON.stringify(file, null, 2) + '\n'),
      branch: s.branch,
    };
    if (sha) body.sha = sha;
    const res = await fetch(contentsUrl(s), { method: 'PUT', headers: headers(s), body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`GitHub 写入失败 ${res.status}: ${await res.text()}`);
    pushed = true;
  }
  return { pulled: merged.length - local.length, pushed, total: merged.filter((i) => i.status !== 'removed').length };
}

function sortForFile(items: LibraryItem[]): LibraryItem[] {
  return [...items].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

let pushTimer: number | undefined;
function schedulePush(): void {
  if (!syncEnabled()) return;
  window.clearTimeout(pushTimer);
  pushTimer = window.setTimeout(() => {
    syncNow().catch((err) => console.warn('[techstation] 自动同步失败', err));
  }, 2000);
}

/** 页面加载时，若开启了同步且距上次拉取超过 2 分钟，则拉一次。 */
export async function pullIfStale(): Promise<void> {
  if (!syncEnabled()) return;
  const last = Number(sessionStorage.getItem(PULL_STAMP_KEY) || 0);
  if (Date.now() - last < 2 * 60 * 1000) return;
  try {
    await syncNow();
  } catch (err) {
    console.warn('[techstation] 同步失败', err);
  }
}

/** 未开启同步时，把站点构建时打包的 library.json 快照合并进来（只读回退）。 */
export async function mergeBuiltSnapshot(baseUrl: string): Promise<void> {
  try {
    const res = await fetch(`${baseUrl}data/library.json`, { cache: 'no-cache' });
    if (!res.ok) return;
    const file = (await res.json()) as LibraryFile;
    if (file.items?.length) {
      const before = loadLibrary();
      const merged = merge(before, file.items);
      if (JSON.stringify(merged) !== JSON.stringify(before)) saveLibrary(merged);
    }
  } catch {
    /* 忽略 */
  }
}
