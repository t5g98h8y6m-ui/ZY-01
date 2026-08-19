"""语料库存储层（SQLite）。表：sources / docs / chunks。
所有写入都在本地，不上传任何数据。"""
import sqlite3, os, time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn=None):
    own = conn is None
    conn = conn or get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sources(
          id INTEGER PRIMARY KEY,
          url TEXT UNIQUE,
          title TEXT,
          domain TEXT,
          source_type TEXT,
          fetched_at TEXT,
          status TEXT,
          lang TEXT
        );
        CREATE TABLE IF NOT EXISTS docs(
          id INTEGER PRIMARY KEY,
          source_id INTEGER,
          url TEXT,
          title TEXT,
          raw_text TEXT,
          created_at TEXT,
          FOREIGN KEY(source_id) REFERENCES sources(id)
        );
        CREATE TABLE IF NOT EXISTS chunks(
          id INTEGER PRIMARY KEY,
          doc_id INTEGER,
          source_id INTEGER,
          idx INTEGER,
          title TEXT,
          category TEXT,
          source TEXT,
          text TEXT,
          meta TEXT,
          FOREIGN KEY(doc_id) REFERENCES docs(id)
        );
        CREATE INDEX IF NOT EXISTS ix_chunks_source ON chunks(source);
        CREATE INDEX IF NOT EXISTS ix_chunks_category ON chunks(category);
        """
    )
    conn.commit()
    if own:
        conn.close()


def add_source(conn, url, title="", source_type="web", domain="", status="ok", lang="zh"):
    cur = conn.execute("SELECT id FROM sources WHERE url=?", (url,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO sources(url,title,domain,source_type,fetched_at,status,lang)"
        " VALUES(?,?,?,?,?,?,?)",
        (url, title, domain, source_type, time.strftime("%Y-%m-%d %H:%M:%S"), status, lang),
    )
    conn.commit()
    return cur.lastrowid


def add_doc(conn, source_id, url, title, raw_text):
    cur = conn.execute(
        "INSERT INTO docs(source_id,url,title,raw_text,created_at) VALUES(?,?,?,?,?)",
        (source_id, url, title, raw_text, time.strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    return cur.lastrowid


def add_chunk(conn, doc_id, source_id, idx, title, category, source, text, meta=""):
    conn.execute(
        "INSERT INTO chunks(doc_id,source_id,idx,title,category,source,text,meta)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (doc_id, source_id, idx, title, category, source, text, meta),
    )


def count_chunks(conn):
    return conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]


def max_chunk_id(conn):
    r = conn.execute("SELECT MAX(id) FROM chunks").fetchone()
    return r[0] or 0


def all_chunks(conn):
    return conn.execute(
        "SELECT id,title,category,source,text,meta FROM chunks"
    ).fetchall()
