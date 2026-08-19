"""多源可达爬虫：把 GitHub / B站 /（可选）抖音 的公开中医内容灌入 corpus.db。

这是 health-corpus 历史待办①「全网爬虫库联网运行」的闭环实现：原 crawler.py 的 web 种子
（中医世家/维基/百度百科）在本沙箱被挡，本脚本改用实测可达的源（GitHub 搜索 API、
B站网页搜索）驱动同一套 db.add_source/add_doc/add_chunk 入库管线。

用法：  python ingest_reachable.py            # 按 sources_reachable.json 全量跑
        python ingest_reachable.py --github    # 只跑 GitHub
        python ingest_reachable.py --bili      # 只跑 B站
依赖：  requests（已装）；同目录 db.py / bili_fetcher.py / douyin_fetcher.py
"""
import os
import sys
import json
import time
import base64
import requests
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from db import get_conn, init_db, add_source, add_doc, add_chunk, count_chunks
import bili_fetcher
import douyin_fetcher

UA = "Mozilla/5.0 (compatible; HealthKB-Crawler/0.2; +local)"
GH_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": UA}


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


# ---------------- GitHub ----------------
def github_search_repos(keyword, per_page=3):
    url = (f"https://api.github.com/search/repositories?q={quote(keyword)}"
           f"&sort=stars&order=desc&per_page={per_page}")
    try:
        r = requests.get(url, headers=GH_HEADERS, timeout=20)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as e:
        print(f"[github] 搜索失败 {keyword!r}: {e}")
        return []


def github_repo_markdown(owner, repo):
    """抓取仓库 README（单请求，避免触发匿名 60/hr 限流）。"""
    try:
        r = requests.get(f"https://api.github.com/repos/{owner}/{repo}/readme",
                         headers=GH_HEADERS, timeout=20)
        r.raise_for_status()
        d = r.json()
        if d.get("encoding") == "base64":
            return base64.b64decode(d["content"]).decode("utf-8", "ignore")
    except Exception:
        return ""
    return ""


def ingest_github(conn, cfg):
    total = 0
    for entry in cfg.get("keywords", []):
        kw, cat = entry["kw"], entry["category"]
        repos = github_search_repos(kw, per_page=cfg.get("per_keyword_repos", 3))
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
            time.sleep(1.0)  # 礼貌限速，避免触发 GitHub 匿名限流
    return total


# ---------------- Bilibili ----------------
def ingest_bili(conn, cfg):
    total = 0
    for kw in cfg.get("keywords", []):
        items = bili_fetcher.fetch(kw, limit=cfg.get("per_keyword_videos", 10),
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


# ---------------- Douyin（需 cookie） ----------------
def ingest_douyin(conn, cfg):
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


def main():
    only = set(sys.argv[1:])
    conn = get_conn()
    init_db(conn)
    before = count_chunks(conn)
    cfg = json.load(open(os.path.join(HERE, "sources_reachable.json"), encoding="utf-8"))

    n_g = n_b = n_d = 0
    if (not only or "--github" in only) and cfg["github"]["enabled"]:
        print("== GitHub ==")
        n_g = ingest_github(conn, cfg["github"])
    if (not only or "--bili" in only) and cfg["bilibili"]["enabled"]:
        print("== Bilibili ==")
        n_b = ingest_bili(conn, cfg["bilibili"])
    if (not only or "--douyin" in only):
        print("== Douyin ==")
        n_d = ingest_douyin(conn, cfg["douyin"])

    after = count_chunks(conn)
    conn.close()
    print(f"\n完成：新增文档 GitHub={n_g} B站={n_b} 抖音={n_d}；"
          f"chunks {before} → {after}（净增 {after - before}）")


if __name__ == "__main__":
    main()
