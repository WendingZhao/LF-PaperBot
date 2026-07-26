# LF-PaperBot

每日光场图像底层视觉论文追踪与分析系统。项目基于 [RS-PaperClaw](https://github.com/thinson/RS-PaperClaw) 的流水线思路重构，聚焦光场超分、去噪、去模糊、低光增强、去遮挡及恢复重建。

## 能力

- 从 arXiv 的 `cs.CV`、`eess.IV`、`physics.optics` 获取最近论文
- 关键词硬筛 + 火山方舟语义筛选，最多精选 5 篇
- 下载入选 PDF，生成中文结构化报告和 GitHub Issue
- 识别 arXiv 新版本并更新原 Issue
- 生成 Markdown 日报、JSON 索引和响应式 GitHub Pages
- GitHub Actions 每天北京时间 09:00 自动运行

## 领域范围

纳入光场空间/角度超分、去噪、去模糊、低光增强、去遮挡、去雨去雾、重建/插值、压缩伪影去除和质量增强。排除通用单幅图像方法、纯深度估计、分类分割、通用 NeRF/3DGS、新视点生成和光场显示。

## 本地使用

需要 Python 3.10+、Poppler（`pdftotext`、`pdftoppm`）和以下环境变量：

```powershell
Copy-Item .env.example .env
python -m pip install -r requirements.txt
python -m lf_paperbot doctor
python -m lf_paperbot fetch --dry-run --no-llm
python -m lf_paperbot run
```

主要命令：

```text
python -m lf_paperbot doctor
python -m lf_paperbot fetch --dry-run [--date YYYYMMDD] [--no-llm]
python -m lf_paperbot run [--date YYYYMMDD] [--force]
python -m lf_paperbot paper <arxiv_id>
python -m lf_paperbot reconcile --date YYYYMMDD
```

## GitHub 配置

1. 在仓库 Settings → Secrets and variables → Actions 中添加重新生成的 `ARK_API_KEY`。
2. Settings → Pages 将 Source 设为 **GitHub Actions**。
3. 手动运行 `Daily LF PaperBot`，确认 Issue、日报与索引生成。

`GITHUB_TOKEN` 使用 Actions 内置 token，无需额外创建 PAT。不要把 API Key 写入 `.env.example`、workflow、Issue 或日志。

## 输出

- `papers/index.json`：论文索引和版本状态
- `daily_reports/YYYYMM/YYYYMMDD.md`：每日精选
- `docs/data/index.json`：静态页面数据
- `docs/assets/previews/*.webp`：每篇一张首页预览

## 许可证与致谢

本项目使用 Apache License 2.0。感谢 [thinson/RS-PaperClaw](https://github.com/thinson/RS-PaperClaw) 提供的开源参考实现；LF-PaperBot 已针对光场底层视觉重新设计筛选、数据结构、报告和发布流程。
