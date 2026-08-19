"""V2EX 社区 fetcher（pure，不碰 DB）。

V2EX 有公开 API（无需登录），但本沙箱直连被挡，需走代理。
代理从环境变量读取（优先级：V2EX_PROXY > HTTPS_PROXY > HTTP_PROXY）。

端点：
  - 热帖：     https://www.v2ex.com/api/topics/hot.json
  - 节点信息： https://www.v2ex.com/api/nodes/show.json?name=<node>
  - 节点主题： https://www.v2ex.com/api/topics/show.json?node_id=<id>&page=<n>
  - 主题回复： https://www.v2ex.com/api/replies/show.json?topic_id=<id>

返回 [{title,url,text,node}]，text 含主题正文 + 前若干回复（拼成可读全文）。

用法（单独测试）：
    import v2ex_fetcher
    items = v2ex_fetcher.fetch(node_names=["health","food"], hot=True, limit=10)
"""
import os
import json
import urllib.request
import urllib.error
from urllib.parse import urlencode

UA = "HealthKB-Crawler/0.2 (+local)"
API = "https://www.v2ex.com/api"


def _opener():
    proxy = os.environ.get("V2EX_PROXY") or os.environ.get("HTTPS_PROXY") \
        or os.environ.get("HTTP_PROXY") or ""
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        return urllib.request.build_opener(handler)
    return urllib.request.build_opener()


def _get_json(path, params=None):
    url = API + path
    if params:
        url += "?" + urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with _opener().open(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def _get_node_id(name):
    try:
        d = _get_json("/nodes/show.json", {"name": name})
        return d.get("id")
    except Exception:
        return None


def _topic_text(topic, with_replies=5):
    parts = []
    content = (topic.get("content") or "").strip()
    if content:
        parts.append(content)
    if with_replies and topic.get("replies", 0) > 0:
        try:
            reps = _get_json("/replies/show.json", {"topic_id": topic["id"]})
            for rep in reps[:with_replies]:
                c = (rep.get("content") or "").strip()
                if c:
                    parts.append("— " + c)
        except Exception:
            pass
    return "\n".join(parts).strip()


def fetch(node_names=None, hot=True, limit=10, with_replies=5):
    """抓取 V2EX 热帖 + 指定节点的主题全文。"""
    node_names = node_names or []
    out = []
    seen = set()

    def _collect(topics):
        for t in topics[:limit]:
            tid = t.get("id")
            if not tid or tid in seen:
                continue
            seen.add(tid)
            text = _topic_text(t, with_replies=with_replies)
            if not text:
                continue
            out.append({
                "title": t.get("title", ""),
                "url": f"https://www.v2ex.com/t/{tid}",
                "text": text,
                "node": (t.get("node", {}) or {}).get("title", "") or t.get("node_name", ""),
            })

    if hot:
        try:
            _collect(_get_json("/topics/hot.json"))
        except Exception as e:
            print(f"  [v2ex] 热帖抓取失败：{e}")

    for name in node_names:
        nid = _get_node_id(name)
        if not nid:
            print(f"  [v2ex] 节点未找到：{name}")
            continue
        try:
            _collect(_get_json("/topics/show.json", {"node_id": nid, "page": 1}))
        except Exception as e:
            print(f"  [v2ex] 节点 {name} 抓取失败：{e}")

    return out


if __name__ == "__main__":
    items = fetch(node_names=["health", "food", "nutrition"], hot=True, limit=8)
    for i, it in enumerate(items, 1):
        print(f"{i}. [{it['node']}] {it['title']}\n   {it['url']}  ({len(it['text'])}字)\n")
