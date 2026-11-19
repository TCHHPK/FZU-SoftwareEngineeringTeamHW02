CREATE TABLE IF NOT EXISTS mindmap_nodes (
  node_id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  parent_id INTEGER REFERENCES mindmap_nodes(node_id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  level INTEGER NOT NULL DEFAULT 1,
  summary TEXT NOT NULL DEFAULT '',
  evidence_chunk_key TEXT NOT NULL DEFAULT '',
  evidence_page INTEGER,
  seq INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_mn_session ON mindmap_nodes(session_id,parent_id,seq);
