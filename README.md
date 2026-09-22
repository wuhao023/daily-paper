# Tech Station · 机器人 & AI 每日站

> 一个完全免费、自动运行的个人「技术站」：每天推荐最新的机器人 / AI 论文（arXiv）与 GitHub 项目，追踪你关心的实验室与学者，并附带一套从零开始的机器人学理论课程。

🌐 **在线站点：<https://wuhao023.github.io/daily-paper/>**

## 功能

| 页面 | 说明 |
| --- | --- |
| 📄 今日论文 | 按个人兴趣画像打分排序的 arXiv 新论文，双栏卡片：左侧摘要，右侧论文配图（无配图时用 PDF 首页预览） |
| 🐙 GitHub 项目 | 与机器人 / AI 相关的新项目与热门项目，附 README 配图 |
| 🎓 学者追踪 | 按实验室 → 学者三级浏览 UC Berkeley、Stanford、CMU、MIT、ETH 等实验室的最新工作 |
| 📐 理论基础 | 9 个领域、45 个主题的机器人学学习路线：建模、控制 / MPC、规划、强化学习、状态估计、仿真工具、Sim-to-Real、真机部署；KaTeX 公式 + 全部免费的经典资料 + 自测题，学习进度保存在浏览器 |
| 🔍 搜索 | 全文 / 仅关键词两种模式，支持 `AND` / `OR` / `-排除` / `"短语"` 布尔查询与关键词组合 |
| 📚 我的书库 | 点赞、稍后读、不感兴趣；反馈会反哺推荐（点赞 = 正样本，不感兴趣 = 负样本） |
| 🔗 分享 | 每条推荐有独立详情页与分享链接（含 Open Graph 卡片） |
| 🔄 刷新 | 一键触发 GitHub Actions 重新抓取（快速模式，跳过学者追踪，约 4 分钟；若已有任务在跑则直接接管其进度） |

## 零成本原则

整个项目不花一分钱，也不依赖任何付费 API：

- **托管**：公开仓库 + GitHub Pages（免费）
- **计算**：GitHub Actions 每日定时任务（公开仓库免费）
- **推荐算法**：本地 embedding 模型 [`BAAI/bge-small-en-v1.5`](https://huggingface.co/BAAI/bge-small-en-v1.5)（通过 [fastembed](https://github.com/qdrant/fastembed) 在 CPU 上运行）+ 余弦相似度 + 关键词加权，不调用任何 LLM / embedding 云服务
- **数据**：arXiv 公开 API、GitHub REST API（Actions 自带的 `GITHUB_TOKEN` 即可），所有数据以 JSON 文件形式提交在 `data/` 目录
- **用户状态**：书库与学习进度存在浏览器 `localStorage`，可选地用你自己的 GitHub token 同步到仓库

## 架构

```
profile/            兴趣画像与追踪名单（你唯一需要经常改的地方）
  interests.yaml    arXiv 分类、兴趣描述、关键词加权 / 屏蔽
  labs.yaml         追踪的实验室与学者
pipeline/           Python 管道（uv 管理）
  techstation/      抓取 arXiv / GitHub → 配图 → embedding 打分 → 写入 data/
data/               管道产出（每日 JSON、搜索索引、PDF 缩略图、书库）
site/               Astro 静态站点，构建时读取 data/ 生成全部页面
.github/workflows/  daily.yml：每天 UTC 06:30 运行管道 → 提交数据 → 构建 → 发布到 Pages
```

每日流程：`Actions 定时触发 → uv run techstation → git commit data/ → npm run build → deploy-pages`。
向 `main` 推送代码也会自动重新构建并发布站点（仅改动 `data/` 或 Markdown 不会触发）。

## 本地运行

需要 Python ≥ 3.10（用 [uv](https://docs.astral.sh/uv/)）与 Node ≥ 20。

```bash
# 1. 跑一次管道（首次会下载约 130 MB 的 embedding 模型到 pipeline/.cache）
cd pipeline
GITHUB_TOKEN=<可选，提高 GitHub API 限额> uv run techstation

# 2. 本地预览站点
cd ../site
npm ci
npm run dev            # http://localhost:4321/

# 生产构建（与 Actions 中一致）
BASE_PATH=/daily-paper/ PUBLIC_REPO=<用户名>/daily-paper npm run build
```

## 部署到自己的账号

1. Fork 或复制本仓库为**公开**仓库
2. `Settings → Pages → Source` 选 **GitHub Actions**
3. `Settings → Actions → General → Workflow permissions` 选 **Read and write permissions**
4. 修改 `profile/interests.yaml` 与 `profile/labs.yaml`，推送到 `main`
5. 在 `Actions → daily → Run workflow` 手动跑一次；之后每天自动更新

若想使用「刷新推荐」与「书库同步到仓库」功能，在站点的 ⚙️ 设置页粘贴一个 [fine-grained token](https://github.com/settings/personal-access-tokens/new)（仅授予本仓库 `Contents: Read and write` 与 `Actions: Read and write`）。token 只保存在你的浏览器里。

## 定制推荐

- `profile/interests.yaml`：`arxiv.categories` 决定抓哪些分类；`interests` 每条一句自然语言，会被 embedding 成兴趣向量；`keywords.boost` / `keywords.mute` 做关键词加权与屏蔽
- `profile/labs.yaml`：按实验室列出学者姓名（arXiv 作者名），非 ASCII 名称需手写 `slug`
- 在站点上点「♥ 点赞」「✕ 不感兴趣」，反馈会写入 `data/library.json` 并在下一次运行时参与打分

## 技术栈

Python · [uv](https://docs.astral.sh/uv/) · [fastembed](https://github.com/qdrant/fastembed) · [PyMuPDF](https://pymupdf.readthedocs.io/) · [Astro](https://astro.build/) · [MiniSearch](https://github.com/lucaong/minisearch) · [KaTeX](https://katex.org/) · GitHub Actions · GitHub Pages

## 声明

该项目的原作者是： https://github.com/Zweisteine96/daily-paper 我只是fork了repo进行个性化的调整

## License

[MIT](LICENSE)
