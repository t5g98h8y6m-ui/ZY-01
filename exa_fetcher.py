"""Exa 语义搜索引擎 fetcher（pure，不碰 DB）。

Exa 提供「语义/关键词」混合检索 + 正文明文返回，适合作为健康系统的
「全网语义搜索」通道（弥补 GitHub/B站 只能关键词匹配的短板）。

依赖：requests（隔离 venv 已装）。
认证：EXA_API_KEY（exa.ai 后台申请，环境变量或显式传入）。

用法（单独测试）：
    import exa_fetcher
    items = exa_fetcher.search("中医 食疗 脾胃", max_results=10)
    for it in items:
        print(it["title"], it["url"], len(it["text"]))
"""
import os
import json
import urllib.request
import urllib.error

UA = "HealthKB-Crawler/0.2 (+local)"
SEARCH_URL = "https://api.exa.ai/search"


def _post(url, payload, api_key):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "User-Agent": UA,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def search(query, max_results=10, api_key=None, use_neural=False):
    """语义/关键词检索，返回 [{title,url,text,publishedDate,author}]。

    - use_neural=True 走 Exa 神经检索（语义相近），=False 走关键词（更精确）。
    - api_key 缺失时回退读 EXA_API_KEY 环境变量；再缺失抛 ValueError。
    """
    api_key = api_key or os.environ.get("EXA_API_KEY", "")
    if not api_key:
        raise ValueError("缺少 EXA_API_KEY：请在 exa.ai 申请后传入或设置环境变量 EXA_API_KEY")

    payload = {
        "query": query,
        "numResults": max_results,
        "type": "neural" if use_neural else "keyword",
        "contents": {"text": True, "highlights": True},
    }
    try:
        data = _post(SEARCH_URL, payload, api_key)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:200]
        raise RuntimeError(f"Exa API HTTP {e.code}: {body}")
    except Exception as e:
        raise RuntimeError(f"Exa 请求失败：{e}")

    out = []
    for r in data.get("results", []):
        text = (r.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "title": r.get("title", "") or r.get("url", ""),
            "url": r.get("url", ""),
            "text": text,
            "publishedDate": r.get("publishedDate", ""),
            "author": (r.get("author") or ""),
        })
    return out


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "中医 食疗 脾胃调理"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    items = search(q, max_results=n)
    for i, it in enumerate(items, 1):
        print(f"{i}. {it['title']}\n   {it['url']}  ({len(it['text'])}字)\n")
