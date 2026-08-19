"""B站（Bilibili）爬取能力：通过 wbi 签名调用官方搜索 API，免登录获取视频标题/简介/作者。

实测（2026-08-18）：
  - search.bilibili.com 网页为纯 JS 渲染空壳，HTML 仅含 bvid 骨架链接，标题需 XHR 加载。
  - api.bilibili.com/x/web-interface/wbi/search/all/v2 需 w_rid 签名（wbi 算法）+ Referer，
    裸调用返回 {"code":0,"data":{"v_voucher":...}} 挑战。本模块实现 wbi 签名，稳定可用。

合规：仅采集公开视频的元数据（标题/简介/作者/链接），不下载音视频流。
"""
import re
import time
import hashlib
import urllib.parse
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}

# wbi 混序表（64→32）
_WBI_ORI = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
            33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
            26, 17, 0, 1, 57, 22, 25, 54, 21, 56, 59, 6, 60, 34, 4, 51, 20, 44, 36, 52, 11, 30]
_wbi_cache = {}


def _get_wbi_keys():
    if _wbi_cache:
        return _wbi_cache["img"], _wbi_cache["sub"]
    r = requests.get("https://api.bilibili.com/x/web-interface/nav",
                     headers=HEADERS, timeout=20)
    d = r.json()["data"]["wbi_img"]
    img = d["img_url"].rsplit("/", 1)[-1].split(".")[0]
    sub = d["sub_url"].rsplit("/", 1)[-1].split(".")[0]
    _wbi_cache["img"], _wbi_cache["sub"] = img, sub
    return img, sub


def _mixin_key(raw: str) -> str:
    return "".join(raw[i] for i in _WBI_ORI)[:32]


def sign(params: dict) -> str:
    """返回已签名的 query 字符串（含 w_rid）。"""
    img, sub = _get_wbi_keys()
    mixin = _mixin_key(img + sub)
    p = dict(sorted(params.items()))
    p["wts"] = int(time.time())
    p = dict(sorted(p.items()))
    query = urllib.parse.urlencode(p)
    w_rid = hashlib.md5((query + mixin).encode()).hexdigest()
    return f"{query}&w_rid={w_rid}"


def search(keyword, limit=20, timeout=20):
    """wbi 签名搜索，返回 [{bvid,title,author,desc,url}]（去重、保序）。"""
    base = "https://api.bilibili.com/x/web-interface/wbi/search/all/v2"
    q = sign({"keyword": keyword, "page": 1, "web_location": "333.1007"})
    try:
        r = requests.get(f"{base}?{q}", headers=HEADERS, timeout=timeout)
        j = r.json()
    except Exception as e:
        print(f"[bili] 搜索请求失败 {keyword!r}: {e}")
        return []
    if j.get("code") != 0:
        print(f"[bili] 搜索返回 code={j.get('code')} msg={j.get('message')}")
        return []
    out, seen = [], set()
    for group in j.get("data", {}).get("result", []):
        if group.get("result_type") != "video":
            continue
        for v in group.get("data", []):
            bv = v.get("bvid")
            if not bv or bv in seen:
                continue
            seen.add(bv)
            title = re.sub("<[^>]+>", "", v.get("title", ""))
            title = urllib.parse.unquote(title).strip()
            out.append({
                "bvid": bv,
                "title": title,
                "author": v.get("author", ""),
                "desc": re.sub("<[^>]+>", "", v.get("description", "")),
                "url": f"https://www.bilibili.com/video/{bv}",
            })
            if len(out) >= limit:
                break
        if len(out) >= limit:
            break
    return out


def fetch(keyword, limit=20, with_desc=True):
    """一条龙：搜索即含简介，with_desc 仅保持接口兼容。"""
    items = search(keyword, limit=limit)
    if not with_desc:
        for it in items:
            it.pop("desc", None)
    return items


if __name__ == "__main__":
    import sys
    kws = sys.argv[1:] or ["倪海厦", "中医", "针灸"]
    for kw in kws:
        res = fetch(kw, limit=5)
        print(f"\n## {kw} -> {len(res)} 条")
        for x in res:
            print(f"  {x['bvid']}  {x['title'][:40]}  @{x['author'][:12]}  desc={len(x.get('desc',''))}字")
