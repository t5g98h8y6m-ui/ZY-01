"""抖音（Douyin）爬取能力：加入健康系统工作台。

实测结论（2026-08-18）：
  - 抖音搜索 API (aweme/v1/web/search/item) 裸调用返回 {"status_code":2483,"status_msg":"请先登录"}，
    且需 X-Bogus / a_bogus 签名；纯服务端无法免登录搜索。
  - 抖音搜索页 / 首页 HTML 为纯 JS 渲染空壳（<body></body>），无服务端数据。
  - 单个视频页 https://www.douyin.com/video/<id> 仍内嵌 RENDER_DATA（含 desc/author/statistics），
    因此「粘贴分享链接 → 抽取结构化信息」是免登录可用路径。

能力：
  - get_video(分享链接或视频id): 解析 RENDER_DATA，返回 {desc,author,statistics,create_time,...}。
  - search(关键词, cookie, signer): 登录态搜索（需用户 Cookie + 签名函数），未提供则明确报错不静默失败。

合规：仅抽取公开视频的元数据/文案，不下载音视频流。
"""
import re
import json
import time
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Referer": "https://www.douyin.com/"}

_RENDER_RE = re.compile(r'RENDER_DATA\s*=\s*"(.*?)"\s*;?\s*</script>', re.S)


def resolve(video_id_or_url: str) -> str:
    """接受 v.douyin.com 短链、www.douyin.com/video/<id>、或纯 id，返回纯数字 video_id。"""
    s = video_id_or_url.strip()
    if re.fullmatch(r"\d{15,20}", s):
        return s
    try:
        r = requests.get(s, headers=HEADERS, allow_redirects=True, timeout=20)
        final = r.url
    except Exception:
        final = s
    m = re.search(r"/video/(\d{15,20})", final)
    if m:
        return m.group(1)
    # 短链有时带 ?previous_page=... 内含 id
    m2 = re.search(r"video_id=(\d{15,20})", final)
    if m2:
        return m2.group(1)
    raise ValueError(f"无法从 {video_id_or_url!r} 解析出抖音 video_id")


def _extract_render(html: str):
    m = _RENDER_RE.search(html)
    if not m:
        return None
    raw = m.group(1)
    # 还原 HTML 转义（RENDER_DATA 内部引号被转成 &quot;）
    raw = (raw.replace("&quot;", '"')
              .replace("&amp;", "&")
              .replace("&lt;", "<")
              .replace("&gt;", ">")
              .replace("&nbsp;", " "))
    try:
        return json.loads(raw)
    except Exception:
        return None


def _find_aweme(obj):
    """递归寻找含 desc+author+statistics 的视频对象。"""
    if isinstance(obj, dict):
        if "desc" in obj and "author" in obj and ("statistics" in obj or "aweme_id" in obj):
            return obj
        for v in obj.values():
            r = _find_aweme(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_aweme(v)
            if r:
                return r
    return None


def get_video(video_id_or_url: str, cookie: str = "", timeout: int = 20):
    """抽取单个抖音视频的结构化信息。返回 dict 或 None。"""
    vid = resolve(video_id_or_url)
    headers = dict(HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    url = f"https://www.douyin.com/video/{vid}"
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        print(f"[douyin] 视频页请求失败 {vid}: {e}")
        return None
    data = _extract_render(r.text)
    if not data:
        print(f"[douyin] 未找到 RENDER_DATA（可能需登录 Cookie）：{vid}")
        return None
    aweme = _find_aweme(data)
    if not aweme:
        return None
    author = aweme.get("author", {}) or {}
    stat = aweme.get("statistics", {}) or {}
    return {
        "video_id": aweme.get("aweme_id") or vid,
        "desc": aweme.get("desc", ""),
        "create_time": aweme.get("create_time"),
        "author_name": author.get("nickname", ""),
        "author_sec_uid": author.get("sec_uid", ""),
        "digg_count": stat.get("digg_count"),
        "comment_count": stat.get("comment_count"),
        "share_count": stat.get("share_count"),
        "music_title": (aweme.get("music") or {}).get("title", ""),
        "url": url,
    }


def search(keyword: str, cookie: str = "", signer=None, count: int = 10):
    """登录态搜索。需要：① 用户登录 Cookie；② 有效的 X-Bogus/a_bogus 签名函数 signer(query_str, ua)->str。
    未提供 Cookie 时直接报错返回 []，不静默假装成功。"""
    if not cookie:
        print("[douyin] search 需要登录 Cookie（status_code 2483）。请提供 cookie=... 再调用。")
        return []
    if signer is None:
        print("[douyin] search 需要签名函数 signer(query, ua)。请提供 signer=... 再调用。")
        return []
    params = {
        "keyword": keyword,
        "count": count,
        "aid": "6383",
        "screen_limit": "1920*1080",
        "start": "0",
        "device_platform": "webapp",
        "version_name": "23.9.0",
    }
    from urllib.parse import urlencode
    q = urlencode(params)
    xb = signer(q, UA)
    url = f"https://www.douyin.com/aweme/v1/web/search/item/?{q}&X-Bogus={xb}"
    try:
        r = requests.get(url, headers={**HEADERS, "Cookie": cookie}, timeout=20)
        j = r.json()
    except Exception as e:
        print(f"[douyin] search 请求失败：{e}")
        return []
    if j.get("status_code") not in (0, None):
        print(f"[douyin] search 返回错误：{j.get('status_code')} {j.get('status_msg')}")
        return []
    return [a for a in j.get("data", {}).get("aweme_list", []) if a]


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python douyin_fetcher.py <抖音分享链接或视频id>")
        sys.exit(1)
    res = get_video(sys.argv[1])
    print(json.dumps(res, ensure_ascii=False, indent=2) if res else "未获取到（可能需登录 Cookie）")
