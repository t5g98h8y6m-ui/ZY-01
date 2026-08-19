# corpus_reachable 分片说明

`export/corpus_reachable.jsonl`（48.8MB，5836 条）因超过 Contents API 单文件舒适区，已分片为 `parts/corpus_part_01..10.jsonl`。

## 数据构成
- github: 805 条（中医相关仓库 README）
- bilibili: 181 条（B站视频元数据）
- rss: 52 条（阮一峰 RSS）
- exa: 4798 条（Exa 语义搜索正文，最丰富）
- 合计 5836 条可达源语料

## 重建
```bash
cat export/parts/corpus_part_*.jsonl > export/corpus_reachable.jsonl
```

## 来源
由 `ingest_reachable.py` 从 `corpus.db` 导出（source_type ∈ github/bilibili/web/rss/exa）。
