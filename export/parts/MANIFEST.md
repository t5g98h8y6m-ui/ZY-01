# corpus_reachable 分片说明

corpus_reachable.jsonl（7853 条）已分片为 parts/corpus_part_01..11.jsonl。

## 数据构成（source_type ∈ github/bilibili/web/rss/exa）
- github: 805 条（中医相关仓库 README）
- bilibili: 181 条（B站视频元数据）
- rss: 52 条（阮一峰 RSS）
- exa: 6815 条（Exa 语义搜索正文，20 个中医主题，最丰富）
- 合计 7853 条可达源语料

## 重建
```bash
cat export/parts/corpus_part_*.jsonl > export/corpus_reachable.jsonl
```
