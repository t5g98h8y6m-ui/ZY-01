"""多源可达爬虫：把 GitHub / B站 / RSS / 直连网页 的公开内容灌入 corpus.db。

这是 health-corpus 历史待办①「全网爬虫库联网运行」的闭环实现：原 crawler.py 的 web 种子
（中医世家/维基/百度百科）在本沙箱被挡或抽不出正文（JS 壳），本脚本改用实测可达的源驱动
同一套 db.add_source/add_doc/add_chunk 入库管线。

2026-08-19 扩源：新增 RSS / 直连网页(web) 两个分支；GitHub 支持 GITHUB_TOKEN 环境变量提额
（匿名 60/hr → 5000/hr），避免扩关键词后被限流。

用法：  python ingest_reachable.py            # 按 sources_reachable.json 全量跑
        python ingest_reachable.py --github   # 只跑 GitHub
        python ingest_reachable.py --bili     # 只跑 B站
        python ingest_reachable.py --rss      # 只跑 RSS
        python ingest_reachable.py --web      # 只跑直连网页
        python ingest_reachable.py --exa      # 只跑 Exa（需 EXA_API_KEY）
        python ingest_reachable.py --v2ex     # 只跑 V2EX（需代理）
        python ingest_reachable.py --cookie   # 只跑登录态频道（需 cookie）
依赖：  requests / feedparser / beautifulsoup4 / lxml（隔离 venv）；同目录 db.py / bili_fetcher.py
        exa_fetcher.py / v2ex_fetcher.py / cookie_fetcher.py（凭证齐了自动启用对应分支）
"""
import os
import sys
import json
import time
import ssl
import base64
import urllib.request
import urllib.error
import urllib.robotparser
from urllib.parse import quote, urlparse, urljoin

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from db import get_conn, init_db, add_source, add_doc, add_chunk, count_chunks
import bili_fetcher
from extract import html_to_text

UA = "Mozilla/5.0 (compatible; HealthKB-Crawler/0.2; +local)"
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# GitHub token 从环境变量读取（不写死），有则 5000/hr，无则匿名 60/hr
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GH_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": UA}
if GH_TOKEN:
    GH_HEADERS["Authorization"] = f"Bearer {GH_TOKEN}"


def chunk_text(text, size=400, overlap=60):
    if not text:
        return []
    out, i, n = [], 0, len(text)
    while i < n:
        out.append(text[i:i + size])
        i += size - overlap
    return out


def doc_exists(conn, source_id, url):
    cur = conn.execute("SELECT 1 FROM docs WHERE source_id=? AND url=?", (source_id, url))
    return cur.fetchone() is not None


def _get(url, timeout=20, headers=None):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX)


# ---------------- GitHub ----------------
def github_search_repos(keyword, per_page=5):
    url = (f"https://api.github.com/search/repositories?q={quote(keyword)}"
           f"&sort=stars&order=desc&per_page={per_page}")
    try:
        r = _get(url, headers=GH_HEADERS)
        return json.load(r).get("items", [])
    except Exception as e:
        print(f"[github] 搜索失败 {keyword!r}: {e}")
        return []


def github_repo_markdown(owner, repo):
    """抓取仓库 README（单请求，避免触发匿名 60/hr 限流）。"""
    try:
        r = _get(f"https://api.github.com/repos/{owner}/{repo}/readme", headers=GH_HEADERS)
        d = json.load(r)
        if d.get("encoding") == "base64":
            return base64.b64decode(d["content"]).decode("utf-8", "ignore")
    except Exception:
        return ""
    return ""


def ingest_github(conn, cfg):
    total = 0
    for entry in cfg.get("keywords", []):
        kw, cat = entry["kw"], entry["category"]
        repos = github_search_repos(kw, per_page=cfg.get("per_keyword_repos", 5))
        for repo in repos:
            full = repo["full_name"]
            html_url = repo["html_url"]
            sid = add_source(conn, html_url, title=f"{full} · {repo.get('description','')[:40]}",
                             source_type="github", domain="github.com", status="ok", lang="zh")
            if doc_exists(conn, sid, html_url):
                print(f"  [skip] 已存在 {full}")
                continue
            md = github_repo_markdown(full.split('/')[0], full.split('/')[1])
            if not md.strip():
                continue
            did = add_doc(conn, sid, html_url, repo.get("description", "") or full, md)
            for i, ch in enumerate(chunk_text(md)):
                add_chunk(conn, did, sid, i, repo.get("description", "") or full, cat, full, ch,
                          meta=json.dumps({"source": "github", "repo": full}, ensure_ascii=False))
            conn.commit()
            total += 1
            print(f"  [github] {full} 入库 {len(md)} 字 / {len(chunk_text(md))} 块")
            time.sleep(0.5)
    return total


# ---------------- Bilibili ----------------
def ingest_bili(conn, cfg):
    total = 0
    for kw in cfg.get("keywords", []):
        items = bili_fetcher.fetch(kw, limit=cfg.get("per_keyword_videos", 12),
                                   with_desc=cfg.get("with_desc", True))
        for it in items:
            url = it["url"]
            sid = add_source(conn, url, title=it["title"], source_type="bilibili",
                             domain="bilibili.com", status="ok", lang="zh")
            if doc_exists(conn, sid, url):
                continue
            text = f"标题：{it['title']}\n简介：{it.get('desc','')}\n链接：{url}"
            did = add_doc(conn, sid, url, it["title"], text)
            for i, ch in enumerate(chunk_text(text)):
                add_chunk(conn, did, sid, i, it["title"], "视频元数据", "bilibili", ch,
                          meta=json.dumps({"source": "bilibili", "bvid": it["bvid"]}, ensure_ascii=False))
            conn.commit()
            total += 1
        print(f"  [bili] {kw} 入库 {len(items)} 条")
        time.sleep(0.5)
    return total


# ---------------- RSS ----------------
def _can_fetch(url):
    host = urlparse(url).netloc
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"https://{host}/robots.txt")
    try:
        rp.read()
        return rp.can_fetch(UA, url)
    except Exception:
        return True


def ingest_rss(conn, cfg):
    import feedparser
    total = 0
    per_feed = int(cfg.get("per_feed", 8))
    for feed_url in cfg.get("feeds", []):
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"  [rss] 解析失败 {feed_url}: {e}")
            continue
        title = parsed.feed.get("title", feed_url) if parsed.get("feed") else feed_url
        print(f"== RSS {title} ({len(parsed.entries)} 条) ==")
        for e in parsed.entries[:per_feed]:
            link = e.get("link", "")
            if not link:
                continue
            etitle = e.get("title", link)
            body = e.get("summary", "") or e.get("description", "")
            full = body
            # 若文章正文可达，试着抓取全文
            if _can_fetch(link):
                try:
                    with _get(link, timeout=15) as r:
                        full = html_to_text(r.read(500000).decode("utf-8", "ignore")) or body
                except Exception:
                    pass
            sid = add_source(conn, link, title=etitle, source_type="rss",
                             domain=urlparse(link).netloc, status="ok", lang="zh")
            if doc_exists(conn, sid, link):
                continue
            text = f"标题：{etitle}\n链接：{link}\n\n{full}"
            did = add_doc(conn, sid, link, etitle, text)
            for i, ch in enumerate(chunk_text(text)):
                add_chunk(conn, did, sid, i, etitle, cfg.get("category", "RSS"),
                          urlparse(feed_url).netloc, ch,
                          meta=json.dumps({"source": "rss"}, ensure_ascii=False))
            conn.commit()
            total += 1
        print(f"  [rss] {title} 入库 {min(per_feed, len(parsed.entries))} 条")
    return total


# ---------------- 直连网页 web ----------------
def ingest_web(conn, cfg):
    total = 0
    for seed in cfg.get("seeds", []):
        url = seed["url"]
        cat = seed.get("category", "网页")
        src = seed.get("source", urlparse(url).netloc)
        if not _can_fetch(url):
            print(f"  [web] robots 禁止 {url}")
            continue
        try:
            with _get(url, timeout=15) as r:
                text = html_to_text(r.read(500000).decode("utf-8", "ignore"))
        except Exception as e:
            print(f"  [web] 抓取失败 {url}: {str(e)[:50]}")
            continue
        if len(text) < 120:
            print(f"  [web] 正文过短({len(text)}字)跳过 {url}")
            continue
        sid = add_source(conn, url, title=seed.get("name", url), source_type="web",
                         domain=urlparse(url).netloc, status="ok", lang="zh")
        if doc_exists(conn, sid, url):
            continue
        did = add_doc(conn, sid, url, seed.get("name", url), text)
        for i, ch in enumerate(chunk_text(text)):
            add_chunk(conn, did, sid, i, seed.get("name", url), cat, src, ch,
                      meta=json.dumps({"source": "web"}, ensure_ascii=False))
        conn.commit()
        total += 1
        print(f"  [web] {url} 入库 {len(text)} 字 / {len(chunk_text(text))} 块")
    return total


# ---------------- Douyin（需 cookie） ----------------
def ingest_douyin(conn, cfg):
    import douyin_fetcher
    if not cfg.get("enabled"):
        return 0
    cookie = cfg.get("cookie", "")
    if not cookie:
        print("  [douyin] 未配置 cookie，跳过")
        return 0
    total = 0
    for kw in cfg.get("keywords", []):
        items = douyin_fetcher.search(kw, cookie=cookie)
        for a in items:
            url = f"https://www.douyin.com/video/{a.get('aweme_id')}"
            sid = add_source(conn, url, title=a.get("desc", "")[:40], source_type="douyin",
                             domain="douyin.com", status="ok", lang="zh")
            if doc_exists(conn, sid, url):
                continue
            text = a.get("desc", "")
            did = add_doc(conn, sid, url, a.get("desc", "")[:40], text)
            for i, ch in enumerate(chunk_text(text)):
                add_chunk(conn, did, sid, i, a.get("desc", "")[:40], "视频文案", "douyin", ch,
                          meta=json.dumps({"source": "douyin"}, ensure_ascii=False))
            conn.commit()
            total += 1
        print(f"  [douyin] {kw} 入库 {len(items)} 条")
    return total


# ---------------- Exa 语义搜索（需 EXA_API_KEY） ----------------
def ingest_exa(conn, cfg):
    if not cfg.get("enabled"):
        return 0
    import exa_fetcher
    api_key = os.environ.get("EXA_API_KEY", "")
    if not api_key:
        print("  [exa] 未设置 EXA_API_KEY，跳过（set 后重跑）")
        return 0
    max_results = int(cfg.get("max_results", 10))
    total = 0
    for q in cfg.get("queries", []):
        cat = q.get("category", "语义搜索") if isinstance(q, dict) else "语义搜索"
        query = q["q"] if isinstance(q, dict) else q
        try:
            items = exa_fetcher.search(query, max_results=max_results, api_key=api_key,
                                       use_neural=cfg.get("use_neural", False))
        except Exception as e:
            print(f"  [exa] 查询失败 {query!r}: {e}")
            continue
        for it in items:
            url = it["url"]
            if not url:
                continue
            sid = add_source(conn, url, title=it["title"], source_type="exa",
                             domain=urlparse(url).netloc, status="ok", lang="zh")
            if doc_exists(conn, sid, url):
                continue
            text = f"标题：{it['title']}\n链接：{url}\n来源：{it.get('author','')} {it.get('publishedDate','')}\n\n{it['text']}"
            did = add_doc(conn, sid, url, it["title"], text)
            for i, ch in enumerate(chunk_text(text)):
                add_chunk(conn, did, sid, i, it["title"], cat, "exa", ch,
                          meta=json.dumps({"source": "exa", "query": query}, ensure_ascii=False))
            conn.commit()
            total += 1
        print(f"  [exa] {query} 入库 {len(items)} 条")
        time.sleep(0.5)
    return total


# ---------------- V2EX（需代理） ----------------
def ingest_v2ex(conn, cfg):
    if not cfg.get("enabled"):
        return 0
    import v2ex_fetcher
    proxy = os.environ.get("V2EX_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if not proxy:
        print("  [v2ex] 未设置代理(V2EX_PROXY/HTTPS_PROXY)，跳过")
        return 0
    items = v2ex_fetcher.fetch(
        node_names=cfg.get("node_names", []),
        hot=cfg.get("hot", True),
        limit=int(cfg.get("limit", 10)),
        with_replies=int(cfg.get("with_replies", 5)),
    )
    total = 0
    cat = cfg.get("category", "V2EX社区")
    for it in items:
        url = it["url"]
        sid = add_source(conn, url, title=it["title"], source_type="v2ex",
                         domain="v2ex.com", status="ok", lang="zh")
        if doc_exists(conn, sid, url):
            continue
        text = f"标题：{it['title']}\n节点：{it['node']}\n链接：{url}\n\n{it['text']}"
        did = add_doc(conn, sid, url, it["title"], text)
        for i, ch in enumerate(chunk_text(text)):
            add_chunk(conn, did, sid, i, it["title"], cat, "v2ex", ch,
                      meta=json.dumps({"source": "v2ex", "node": it["node"]}, ensure_ascii=False))
        conn.commit()
        total += 1
    print(f"  [v2ex] 入库 {total} 条")
    return total


# ---------------- 登录态频道（需 cookie） ----------------
def ingest_cookie(conn, cfg):
    if not cfg.get("enabled"):
        return 0
    import cookie_fetcher
    total = 0
    for ch in cfg.get("channels", []):
        if not ch.get("enabled", True):
            continue
        channel = ch["channel"]
        target = ch.get("target", "")
        cookie = ch.get("cookie", "")
        category = ch.get("category", channel)
        try:
            items = cookie_fetcher.fetch(channel, target, cookie=cookie)
        except NotImplementedError as e:
            print(f"  [cookie:{channel}] 未实现：{e}")
            continue
        except Exception as e:
            print(f"  [cookie:{channel}] 抓取失败：{e}")
            continue
        for it in items:
            url = it.get("url", "")
            if not url:
                continue
            sid = add_source(conn, url, title=it.get("title", ""), source_type=f"cookie:{channel}",
                             domain=urlparse(url).netloc, status="ok", lang="zh")
            if doc_exists(conn, sid, url):
                continue
            text = f"标题：{it.get('title','')}\n链接：{url}\n\n{it.get('text','')}"
            did = add_doc(conn, sid, url, it.get("title", ""), text)
            for i, c in enumerate(chunk_text(text)):
                add_chunk(conn, did, sid, i, it.get("title", ""), category, f"cookie:{channel}", c,
                          meta=json.dumps({"source": f"cookie:{channel}", "target": target}, ensure_ascii=False))
            conn.commit()
            total += 1
        print(f"  [cookie:{channel}] {target} 入库 {len(items)} 条")
        time.sleep(0.5)
    return total


def main():
    only = set(sys.argv[1:])
    conn = get_conn()
    init_db(conn)
    before = count_chunks(conn)
    cfg = json.load(open(os.path.join(HERE, "sources_reachable.json"), encoding="utf-8"))

    n_g = n_b = n_r = n_w = n_d = n_e = n_v = n_c = 0
    if (not only or "--github" in only) and cfg["github"]["enabled"]:
        print("== GitHub ==")
        n_g = ingest_github(conn, cfg["github"])
    if (not only or "--bili" in only) and cfg["bilibili"]["enabled"]:
        print("== Bilibili ==")
        n_b = ingest_bili(conn, cfg["bilibili"])
    if (not only or "--rss" in only) and cfg.get("rss", {}).get("enabled"):
        print("== RSS ==")
        n_r = ingest_rss(conn, cfg["rss"])
    if (not only or "--web" in only) and cfg.get("web", {}).get("enabled"):
        print("== Web ==")
        n_w = ingest_web(conn, cfg["web"])
    if (not only or "--douyin" in only):
        print("== Douyin ==")
        n_d = ingest_douyin(conn, cfg["douyin"])
    if (not only or "--exa" in only) and cfg.get("exa", {}).get("enabled"):
        print("== Exa ==")
        n_e = ingest_exa(conn, cfg["exa"])
    if (not only or "--v2ex" in only) and cfg.get("v2ex", {}).get("enabled"):
        print("== V2EX ==")
        n_v = ingest_v2ex(conn, cfg["v2ex"])
    if (not only or "--cookie" in only) and cfg.get("cookie_channels", {}).get("enabled"):
        print("== Cookie 登录态频道 ==")
        n_c = ingest_cookie(conn, cfg["cookie_channels"])

    after = count_chunks(conn)
    conn.close()
    print(f"\n完成：新增文档 GitHub={n_g} B站={n_b} RSS={n_r} 网页={n_w} 抖音={n_d}"
          f" Exa={n_e} V2EX={n_v} 登录态={n_c}；"
          f"chunks {before} → {after}（净增 {after - before}）")


if __name__ == "__main__":
    main()
