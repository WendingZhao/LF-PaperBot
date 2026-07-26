# LF-PaperBot

每周普通光场图像广义底层视觉论文追踪与分析系统。项目基于 [RS-PaperClaw](https://github.com/thinson/RS-PaperClaw) 的流水线思路重构，覆盖光场超分、恢复、重建、深度与视差估计、重聚焦等方向。

## 能力

- 从 arXiv 的 `cs.CV`、`cs.GR`、`cs.MM`、`eess.IV`、`eess.SP`、`physics.optics` 获取上一自然周论文
- 关键词硬筛 + 火山方舟语义筛选，每周最多精选 5 篇
- 下载入选 PDF，生成中文结构化报告和 GitHub Issue
- 识别 arXiv 新版本并更新原 Issue
- 生成 Markdown 周报、JSON 索引和响应式 GitHub Pages
- GitHub Actions 每周一北京时间 09:00 自动运行
- 支持从 `2026-01-01` 起按自然周回填历史论文

## 领域范围

纳入普通相机、标准微透镜或多相机阵列光场图像的空间/角度超分、去噪、去模糊、低光增强、去遮挡、去雨去雾、稠密重建/视图插值、深度与视差估计、重聚焦、压缩恢复和质量增强。排除通用单幅/双目方法、事件相机光场、光场显微、声学/瞬态/X 射线光场、分类分割、通用 NeRF/3DGS、神经渲染和光场显示。

## 本地使用

需要 Python 3.10+、Poppler（`pdftotext`、`pdftoppm`）和以下环境变量：

```powershell
Copy-Item .env.example .env
python -m pip install -r requirements.txt
python -m lf_paperbot doctor
python -m lf_paperbot fetch --dry-run --no-llm
python -m lf_paperbot run
python -m lf_paperbot backfill --start 20260101
```

主要命令：

```text
python -m lf_paperbot doctor
python -m lf_paperbot fetch --dry-run [--date YYYYMMDD] [--no-llm]
python -m lf_paperbot run [--date YYYYMMDD] [--force]
python -m lf_paperbot backfill [--start YYYYMMDD] [--end YYYYMMDD] [--force]
python -m lf_paperbot paper <arxiv_id>
python -m lf_paperbot reconcile --date YYYYMMDD
```

## GitHub 配置

1. 在仓库 Settings → Secrets and variables → Actions 中添加重新生成的 `ARK_API_KEY`。
2. Settings → Pages 将 Source 设为 **GitHub Actions**。
3. 手动运行 `Weekly LF PaperBot`，确认 Issue、周报与索引生成。
4. 需要历史数据时运行 `LF PaperBot Backfill`；它仅从仓库 Secret 读取 `ARK_API_KEY`。

`GITHUB_TOKEN` 使用 Actions 内置 token，无需额外创建 PAT。不要把 API Key 写入 `.env.example`、workflow、Issue 或日志。

## 输出

- `papers/index.json`：论文索引和版本状态
- `daily_reports/YYYYMM/YYYYMMDD.md`：周报归档（文件日期为统计周期结束日，保留旧路径兼容性）
- `docs/data/index.json`：静态页面数据
- `docs/assets/previews/*.webp`：每篇一张首页预览

## 许可证与致谢

本项目使用 Apache License 2.0。感谢 [thinson/RS-PaperClaw](https://github.com/thinson/RS-PaperClaw) 提供的开源参考实现；LF-PaperBot 已针对光场底层视觉重新设计筛选、数据结构、报告和发布流程。
