# LF-PaperBot

每周普通光场图像广义底层视觉论文追踪与分析系统。项目基于 [RS-PaperClaw](https://github.com/thinson/RS-PaperClaw) 的流水线思路重构，覆盖光场超分、恢复、重建、深度与视差估计、重聚焦等方向。

## 能力

- 从 arXiv、CVF Open Access 和 Crossref 获取候选，按 DOI、规范化标题和 arXiv ID 跨来源去重
- 关键词硬筛 + DeepSeek 语义筛选，每周最多精选 5 篇
- 下载入选 PDF，生成中文结构化报告和 GitHub Issue
- 识别 arXiv 新版本并更新原 Issue
- 生成 Markdown 周报、JSON 索引和响应式 GitHub Pages
- GitHub Actions 每周一北京时间 09:00 自动运行
- 支持从 `2026-01-01` 起按自然周回填历史论文

## 公开来源与查询配置

`LF_SOURCES=arxiv,crossref,cvf` 默认启用三个渠道，无需新增 Secret。可在 `.env` 中调整；云端周更和回填对应 `.github/workflows/daily.yml`、`backfill.yml` 的同名环境变量。

| 渠道 | 覆盖与时间口径 | 全文 |
|---|---|---|
| arXiv | 原有六个类别，按版本更新时间筛选 | 公开 PDF |
| CVF Open Access | 周更自动发现当前及上一年度的 CVPR、ICCV、WACV 主会；历史检索覆盖请求的所有年份，可用 `LF_CVF_VENUES=CVPR2026,WACV2026` 指定 | CVF 官方开放 PDF |
| Crossref | 标题检索 light field / plenoptic，补充会议和期刊 DOI；按发表日期及 DOI 首次登记日期查询 | 有明确 CC 许可的 PDF 才尝试下载，否则用公开摘要 |

CVF 页面常只有发表年份。此类记录按本次首次发现纳入周报，显示“首次发现”，**不代表本周发表**；历史回填时归入回填末期。Crossref 本周登记的旧论文会标记“新登记”。Crossref 并不保证有摘要或开放全文：两者都没有时不生成报告；只有摘要时页面和 Issue 明确标注“仅摘要”，不推测实验数据。来源合并目前使用 DOI、ID 和规范化后的完整标题；改名且没有共同 DOI 的预印本/会议版仍可能需要人工核对。

`CROSSREF_MAILTO` 可选填真实联系邮箱以使用礼貌访问池；`CROSSREF_MAX_PAGES` 默认每条查询最多 20 页（每页 100 条），达到上限会在周报标注检索不完整，也可调小以减少网络请求。单个来源不可用时保留其他来源结果，并在周报显示异常；所有来源均失败则中止，不发布空周报。来源适配与检索词位于 `lf_paperbot/public_sources.py`；底层视觉任务筛选仍位于 `lf_paperbot/domain.py` 和 `analysis.py`。

## 两年历史全量回填

普通周更保留 Top 5；历史回填加 `--all` 则收录全部通过领域筛选的候选，并保留缺少摘要/全文的相关题录（标注“仅题录”，不生成推测性分析）。`--monthly` 按月保存断点，失败月份重试一次；`--commit` 每月提交和推送数据。完成状态见 `papers/backfill_status.json`，重复执行会跳过已完成的月份和已有论文。

```powershell
# 不需要模型 Key：抓取公开元数据，可在本机代理下执行。
python -m lf_paperbot discover --start 20241019 --end 20261019 --output papers/history_20241019_20261019.json
# 使用现有 DeepSeek/GitHub 凭据分析；Actions 可读取仓库内同一快照。
python -m lf_paperbot backfill --start 20241019 --end 20261019 --all --monthly --candidate-file papers/history_20241019_20261019.json
```

GitHub Actions 的 `LF PaperBot Backfill` 可设置日期、`all_papers=true` 和可选 `candidate_file`。历史 Crossref 使用每页 1000 条并翻页到结束，不受周更分页上限限制；CVF 读取 BibTeX 月份但不伪造具体发表日。缺少精确日期时按所属月份/年份的发现记录归档，并标注时间口径。源限流或论文处理失败会记为未完成；只有完整获取且处理成功的批次才标记 complete。快照改变后会重新检查月份，已有 Issue 不会重复创建。

arXiv API 不可用时使用 arXiv 官方网页搜索作为备用，逐页读取完整公开摘要，保留原始投稿日与最新版本日期；历史按首次投稿日期归档，周更按最新版本日期检索。网页格式异常或分页不完整会明确记录失败。

## 领域范围

纳入普通相机、标准微透镜或多相机阵列光场图像的空间/角度超分、去噪、去模糊、低光增强、去遮挡、去雨去雾、稠密重建/视图插值、深度与视差估计、重聚焦、光场图像压缩、压缩恢复、质量增强和质量评价。排除通用单幅/双目方法、事件相机光场、光场显微、MRI、雷达、声学/瞬态/X 射线光场、分类分割、通用 NeRF/3DGS、神经渲染和光场显示。

## 本地使用

需要 Python 3.10+、Poppler（`pdftotext`、`pdftoppm`）和以下环境变量。当前周更使用 DeepSeek 的 OpenAI-compatible 接口：

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
python -m lf_paperbot prune [--apply]
```

调整领域规则后可先运行 `prune` 预览不再符合范围的历史记录，确认后使用 `prune --apply` 从索引和页面中清理并重建受影响周报；GitHub Issue 不会被删除。

## GitHub 配置

1. 在仓库 Settings → Secrets and variables → Actions 中添加 `DEEPSEEK_API_KEY`。Key 只保存在 GitHub Secret，不要写入 `.env`、代码或日志。
2. Settings → Pages 将 Source 设为 **GitHub Actions**。
3. 手动运行 `Weekly LF PaperBot`，确认 Issue、周报与索引生成。
4. 需要历史数据时运行 `LF PaperBot Backfill`；它仅从仓库 Secret 读取 `DEEPSEEK_API_KEY`。

`GITHUB_TOKEN` 使用 Actions 内置 token，无需额外创建 PAT。DeepSeek 配置为：`DEEPSEEK_BASE_URL=https://api.deepseek.com`、`DEEPSEEK_MODEL=deepseek-flash`。旧的 `ARK_*` 变量仍可作为迁移回退，但不再用于 GitHub Actions。

## 输出

- `papers/index.json`：论文索引和版本状态
- `daily_reports/YYYYMM/YYYYMMDD.md`：周报归档（文件日期为统计周期结束日，保留旧路径兼容性）
- `docs/data/index.json`：静态页面数据
- `docs/assets/previews/*.webp`：每篇一张首页预览

## 许可证与致谢

本项目使用 Apache License 2.0。感谢 [thinson/RS-PaperClaw](https://github.com/thinson/RS-PaperClaw) 提供的开源参考实现；LF-PaperBot 已针对光场底层视觉重新设计筛选、数据结构、报告和发布流程。
