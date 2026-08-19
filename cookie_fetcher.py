"""8 个登录态频道 cookie 鉴权抓取框架（pure，不碰 DB）。

这些平台默认需要登录态，靠浏览器 Cookie 才能取到数据。各频道适配器签名统一为：
    fn(target, cookie) -> [{"title","url","text"}]
其中 target 视频道而定（subreddit 名 / 关键词 / 用户主页等）。

⚠️ 重要说明（诚实标注，避免误以为「接上就灵」）：
  - Reddit：公开 JSON API 免登录即可用（cookie 仅提额），本框架已实现可用路径。
  - 雪球 / 小红书 / 小宇宙：best-effort，依赖 cookie + 平台私有端点，未实测，可能需要调参。
  - Twitter/X / Facebook / Instagram / LinkedIn：平台强登录 + 反爬，纯 cookie 抓取极难，
    本框架暂留占位（NotImplementedError），需后续接入官方 API 或专用库，不假装能跑。

Cookie 来源（给用户）：浏览器装「Cookie-Editor」插件 → 打开对应网站登录 → 点插件「导出」得 JSON
→ 把整段 JSON 贴给 Agent 即可（Agent 会解析 name/value 拼成 Cookie 头）。
Cookie 仅本次会话使用，不落盘、不入库。

用法：
    import cookie_fetcher
    items = cookie_fetcher.fetch("reddit", "tcm", target="tcm", cookie="")
    items = cookie_fetcher.fetch("xueqiu", "养生", cookie=<贴来的cookie字符串/JSON>)
"""
import os
import json
import urllib.request
import urllib.error
from urllib.parse import quote, urlencode

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def _cookie_header(cookie):
    """接受 'k=v; k2=v2' 字符串或 Cookie-Editor 导出的 JSON 列表，统一成 'k=v; ...'。"""
    if not cookie:
        return ""
    s = cookie.strip()
    if s.startswith("["):  # Cookie-Editor JSON 列表
        try:
            arr = json.loads(s)
            return "; ".join(f"{c['name']}={c['value']}" for c in arr)
        except Exception:
            return s
    return s


def _opener(cookie_header, proxy=None):
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    opener.addheaders = [("User-Agent", UA)]
    if cookie_header:
        opener.addheaders.append(("Cookie", cookie_header))
    return opener


def _get_json(opener, url):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with opener.open(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------- Reddit（免登录可用） ----------------
def _reddit(target, cookie):
    """target = subreddit 名（不带 r/）。公开 .json 免登录即可抓 hot 帖。"""
    cookie_header = _cookie_header(cookie)
    opener = _opener(cookie_header)
    url = f"https://www.reddit.com/r/{quote(target)}/hot.json?limit=15"
    try:
        data = _get_json(opener, url)
    except Exception as e:
        raise RuntimeError(f"Reddit 抓取失败（可能需 UA/限流，或该 sub 不存在）：{e}")
    out = []
    for c in data.get("data", {}).get("children", []):
        d = c.get("data", {})
        body = (d.get("selftext") or "").strip()
        if not body:
            continue
        out.append({
            "title": d.get("title", ""),
            "url": "https://www.reddit.com" + d.get("permalink", ""),
            "text": body,
        })
    return out


# ---------------- 雪球（best-effort，需 cookie） ----------------
def _xueqiu(target, cookie):
    cookie_header = _cookie_header(cookie)
    if not cookie_header:
        raise ValueError("雪球需要 cookie：请先登录 xueqiu.com 导出 Cookie 贴给我")
    opener = _opener(cookie_header)
    # 雪球要求先访问首页拿到动态 cookie 再查
    try:
        opener.open(urllib.request.Request("https://xueqiu.com/", headers={"User-Agent": UA}), timeout=20).read()
        url = "https://xueqiu.com/statuses/search.json?" + urlencode({
            "count": 20, "comment": 0, "q": target, "sort": "relevance"})
        data = _get_json(opener, url)
    except Exception as e:
        raise RuntimeError(f"雪球抓取失败（cookie 可能过期或端点变更）：{e}")
    out = []
    for st in data.get("list", []) or []:
        d = st.get("data", {}) or {}
        txt = (d.get("text") or "").strip()
        if not txt:
            continue
        out.append({
            "title": (d.get("title") or txt[:30]),
            "url": f"https://xueqiu.com/{d.get('id','')}",
            "text": txt,
        })
    return out


# ---------------- 小红书（best-effort，需 cookie） ----------------
def _xhs(target, cookie):
    cookie_header = _cookie_header(cookie)
    if not cookie_header:
        raise ValueError("小红书需要 cookie：请先登录 xiaohongshu.com 导出 Cookie 贴给我")
    opener = _opener(cookie_header)
    try:
        url = "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes?" + urlencode({
            "keyword": target, "page": 1, "page_size": 20, "search_id": ""})
        data = _get_json(opener, url)
    except Exception as e:
        raise RuntimeError(f"小红书抓取失败（需 x-s 签名或 cookie 过期）：{e}")
    out = []
    for n in (data.get("data", {}) or {}).get("notes", []) or []:
        title = n.get("display_title") or n.get("title") or ""
        desc = n.get("desc") or ""
        if not (title or desc):
            continue
        out.append({
            "title": title,
            "url": f"https://www.xiaohongshu.com/explore/{n.get('id','')}",
            "text": f"{title}\n{desc}",
        })
    return out


# ---------------- 小宇宙播客（best-effort，需 cookie/token） ----------------
def _xiaoyuzhou(target, cookie):
    cookie_header = _cookie_header(cookie)
    if not cookie_header:
        raise ValueError("小宇宙需要 cookie（含 auth token）：请登录 xiaoyuzhoufm.com 导出贴给我")
    opener = _opener(cookie_header)
    gql = {
        "query": "query($q:String!){search(q:$q){podcasts{title,intro,link},episodes{title,shownotes,link}}}",
        "variables": {"q": target},
    }
    req = urllib.request.Request(
        "https://api.xiaoyuzhoufm.com/graphql",
        data=json.dumps(gql).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA, "Cookie": cookie_header},
    )
    try:
        with opener.open(req, timeout=25) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"小宇宙抓取失败（token 可能过期）：{e}")
    out = []
    res = (data.get("data", {}) or {}).get("search", {}) or {}
    for ep in res.get("episodes", []) or []:
        notes = (ep.get("shownotes") or "").strip()
        if not notes:
            continue
        out.append({"title": ep.get("title", ""), "url": ep.get("link", ""), "text": notes})
    return out


# ---------------- 强登录平台：占位，不假装能跑 ----------------
def _not_implemented(channel):
    def _fn(target, cookie):
        raise NotImplementedError(
            f"{channel}：纯 cookie 抓取极难（强登录 + 反爬）。需接入官方 API 或专用库，"
            f"暂未实现。如确需，请告知，我另寻方案。")
    return _fn


REGISTRY = {
    "reddit": _reddit,
    "xueqiu": _xueqiu,
    "xiaohongshu": _xhs,
    "xhs": _xhs,
    "xiaoyuzhou": _xiaoyuzhou,
    "twitter": _not_implemented("Twitter/X"),
    "facebook": _not_implemented("Facebook"),
    "instagram": _not_implemented("Instagram"),
    "linkedin": _not_implemented("LinkedIn"),
}


def fetch(channel, target, cookie=""):
    """统一入口。channel ∈ REGISTRY 键；target 视频道而定；cookie 可为字符串或 Cookie-Editor JSON。"""
    fn = REGISTRY.get(channel.lower())
    if fn is None:
        raise ValueError(f"未知频道 {channel!r}。支持：{', '.join(REGISTRY)}")
    return fn(target, cookie)


def supported():
    return list(REGISTRY.keys())


if __name__ == "__main__":
    print("支持频道：", supported())
    # Reddit 免登录演示
    try:
        items = fetch("reddit", "tcm", cookie="")
        for i, it in enumerate(items[:5], 1):
            print(f"{i}. {it['title']}\n   {it['url']} ({len(it['text'])}字)\n")
    except Exception as e:
        print("Reddit 演示失败：", e)
