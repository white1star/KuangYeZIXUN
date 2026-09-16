CREATE TABLE IF NOT EXISTS sources (
  key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  board TEXT NOT NULL,
  url TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL,
  url_hash TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  title_hash TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  source_key TEXT NOT NULL,
  board TEXT NOT NULL,
  minerals TEXT NOT NULL DEFAULT '[]',
  regions TEXT NOT NULL DEFAULT '[]',
  types TEXT NOT NULL DEFAULT '[]',
  published_at TEXT NOT NULL DEFAULT '',
  fetched_at TEXT NOT NULL,
  cluster_id INTEGER,
  is_primary INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_articles_fetched ON articles(fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_board ON articles(board);
CREATE INDEX IF NOT EXISTS idx_articles_title_hash ON articles(title_hash);
CREATE INDEX IF NOT EXISTS idx_articles_cluster ON articles(cluster_id);

CREATE TABLE IF NOT EXISTS article_clusters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  primary_article_id INTEGER NOT NULL,
  member_count INTEGER NOT NULL DEFAULT 1,
  last_seen TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS prices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  commodity TEXT NOT NULL,
  price_type TEXT NOT NULL,
  value REAL NOT NULL,
  unit TEXT NOT NULL DEFAULT '',
  change REAL,
  change_pct REAL,
  price_date TEXT NOT NULL,
  source_key TEXT NOT NULL,
  raw_label TEXT NOT NULL DEFAULT '',
  fetched_at TEXT NOT NULL,
  UNIQUE(commodity, price_type, price_date, source_key)
);
CREATE INDEX IF NOT EXISTS idx_prices_commodity ON prices(commodity, price_date DESC);

CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  content TEXT NOT NULL,
  contact TEXT NOT NULL DEFAULT '',
  page TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crawl_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_key TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'running',
  items_found INTEGER NOT NULL DEFAULT 0,
  items_new INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT ''
);

CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
  title, summary,
  content='articles', content_rowid='id',
  tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
  INSERT INTO articles_fts(rowid, title, summary) VALUES (new.id, new.title, new.summary);
END;
CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, title, summary) VALUES ('delete', old.id, old.title, old.summary);
END;
CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, title, summary) VALUES ('delete', old.id, old.title, old.summary);
  INSERT INTO articles_fts(rowid, title, summary) VALUES (new.id, new.title, new.summary);
END;
