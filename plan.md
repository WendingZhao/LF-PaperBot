# LF-PaperBot 执行计划

## 目标

- 创建公开仓库 `WendingZhao/LF-PaperBot`，每天北京时间 09:00 由 GitHub Actions 自动运行。
- 仅追踪光场图像底层视觉：空间/角度超分、去噪、去模糊、低光增强、去遮挡、去雨去雾、重建/插值、压缩伪影去除与质量增强。
- 排除通用单幅图像恢复、纯深度估计、识别分割、通用 NeRF/3DGS，以及以新视点生成或显示为主的工作。
- 每周最多精选 5 篇，生成中文周报、单篇 GitHub Issue 和 GitHub Pages 阅读页面。
- 页面部署至 `https://aqu1ver.fun/LF-PaperBot/`，并在 `F:\code\blog` 中添加导航与项目入口。

## 实现

1. 将 RS-PaperClaw 的可复用链路重构为 `lf_paperbot` Python 包，提供 `doctor`、`fetch`、`run`、`paper`、`reconcile` 命令。
2. 从 arXiv 的 `cs.CV`、`eess.IV`、`physics.optics` 抓取最近 3 天候选，以“光场信号 AND 底层视觉信号”硬过滤，再由 LLM 输出结构化相关性和研究价值评分。
3. 使用火山方舟 OpenAI-compatible 接口，Base URL 为 `https://ark.cn-beijing.volces.com/api/coding/v3`，模型默认为 `ark-code-latest`；Key 仅通过 `ARK_API_KEY` Secret 注入。
4. 使用 arXiv 基础 ID 去重；新版本更新原 Issue。每篇只保存一张首页 WebP，不保存 PDF。
5. 生成 `papers/index.json`、`daily_reports/YYYYMM/YYYYMMDD.md` 和 `docs/data/index.json`，静态页面支持日期、任务标签、搜索和详情阅读。
6. 配置 CI、每周一定时任务与 Pages 部署；无入选论文时仍生成空周报。
7. 在博客 `src/site.config.ts` 和 `src/pages/projects/index.astro` 添加入口，只提交这两个文件并保留博客现有未提交依赖变更。

## 验收

- 正确纳入光场超分、去噪、去模糊、低光、去遮挡等论文，并排除深度估计、通用 NeRF/3DGS 等误报。
- LLM 异常时可重试并降级；重复运行和 arXiv 版本更新不产生重复 Issue。
- GitHub Actions、Pages、桌面/移动页面和博客入口正常，仓库及历史中不存在 API Key。

## 安全前提

聊天中公开过的旧 Key 必须撤销。实现和发布只使用重新生成并保存于 GitHub Secret `ARK_API_KEY` 的新 Key。
