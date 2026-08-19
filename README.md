# ZY-01 · 健康系统可达源爬取能力

本仓库同步健康系统（`health-corpus`）中「不依赖登录态 / 代理即可抓取」的外网通道能力，作为版本化备份与跨环境复用点。

## 包含

| 文件 | 作用 |
|------|------|
| `bili_fetcher.py` | B站 **wbi 签名搜索**（返回视频标题/简介/作者/链接），无需登录 |
| `douyin_fetcher.py` | 抖音爬取：视频页 `RENDER_DATA` 解析（免登录）；搜索需登录态 Cookie |
| `ingest_reachable.py` | 多源入库编排：把 GitHub 仓库 README + B站视频元数据 灌入 `corpus.db` |
| `sources_reachable.json` | 可入源头配置（关键词、上限） |
| `export/` | 已从 `corpus.db` 导出的语料（jsonl，纯文本，可版本控制） |

## 用法

```bash
# B站搜索（wbi 签名，免登录）
python bili_fetcher.py 倪海厦 针灸

# 抖音视频解析（粘贴分享链接即可，免登录）
python douyin_fetcher.py get_video https://v.douyin.com/xxxx/

# 多源入库到 corpus.db
python ingest_reachable.py
```

## 说明

- **`corpus.db`（94MB 二进制）不入库**，请用 `export/` 中的 jsonl 同步语料，避免大文件进 git。
- GitHub 公开读取走 `api.github.com`（匿名 60 req/h）；更高限额 / 私有库请用 `gh` + PAT（`gh auth login --with-token`）。
- 抖音搜索 API 强制登录（`status_code 2483`）+ 需签名，`douyin_fetcher.search()` 未给 Cookie 时明确报错，不静默失败。
- 本机 `gh` 已登录账号 `t5g98h8y6m-ui`，对 ZY-01 有完整读写权限（`push/admin:true`）。
