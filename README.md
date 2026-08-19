# ZY-01 · 健康系统可达源爬取能力

本仓库同步健康系统（`health-corpus`）的外网通道能力，作为版本化备份与跨环境复用点。覆盖「零配置可达源」与「凭证激活源（Exa/V2EX/登录态）」两类。

## 包含

| 文件 | 作用 | 激活条件 |
|------|------|----------|
| `bili_fetcher.py` | B站 **wbi 签名搜索**（视频标题/简介/作者/链接） | 免登录 ✅ |
| `douyin_fetcher.py` | 抖音爬取：视频页 `RENDER_DATA` 解析（免登录）；搜索需 Cookie | 解析免登录 ✅ |
| `exa_fetcher.py` | Exa **语义搜索**（正文明文返回） | 需 `EXA_API_KEY` |
| `v2ex_fetcher.py` | V2EX 社区热帖 + 节点全文 | 需代理 `V2EX_PROXY` |
| `cookie_fetcher.py` | 8 登录态频道通用 cookie 框架（Reddit 免登录可用） | 需 cookie（Reddit 除外） |
| `ingest_reachable.py` | 多源入库编排：把各通道内容灌入 `corpus.db` | — |
| `sources_reachable.json` | 可入源头配置（关键词/节点/cookie 位） | — |
| `export/` | 已从 `corpus.db` 导出的「可达源语料」（jsonl，纯文本） | — |

## 用法

```bash
# B站搜索（wbi 签名，免登录）
python bili_fetcher.py 倪海厦 针灸

# 抖音视频解析（粘贴分享链接即可，免登录）
python douyin_fetcher.py get_video https://v.douyin.com/xxxx/

# 多源入库到 corpus.db（GitHub/B站/RSS/网页 默认开）
python ingest_reachable.py

# 凭证激活源（各自需先设环境变量 / 填 cookie）
export EXA_API_KEY=xxx && python ingest_reachable.py --exa
export V2EX_PROXY=http://127.0.0.1:7890 && python ingest_reachable.py --v2ex
python ingest_reachable.py --cookie
```

## 说明

- **`corpus.db`（94MB 二进制）不入库**，请用 `export/` 中的 jsonl 同步语料，避免大文件进 git。
- GitHub 公开读取走 `api.github.com`（匿名 60 req/h）；更高限额用 `export GITHUB_TOKEN=xxx`（→ 5000/hr）。
- Exa/V2EX/登录态频道脚手架已就绪，凭证齐了把 `sources_reachable.json` 对应 `enabled` 置 `true` 即可跑。
- 登录态频道 Cookie 仅运行时使用、不落盘；Twitter/FB/IG/LinkedIn 纯 cookie 抓取极难，框架暂占位。
- 本机 `gh` 已登录 `t5g98h8y6m-ui`，对 ZY-01 有完整读写权限。
