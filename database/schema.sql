-- ADAPTFIT database schema
-- Reproduced exactly from TRD Section 5.

CREATE TABLE IF NOT EXISTS adaptations (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  evidence_source TEXT
);

CREATE TABLE IF NOT EXISTS adaptation_requirements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  adaptation_id TEXT NOT NULL REFERENCES adaptations(id),
  factor TEXT NOT NULL,
  min_value REAL,
  max_value REAL,
  unit TEXT,
  weight REAL NOT NULL CHECK (weight >= 0),
  is_critical INTEGER NOT NULL DEFAULT 0,
  transfer_tolerance REAL,        -- max acceptable |B - A| before flagging
  tolerance_type TEXT DEFAULT 'absolute',  -- "relative" (fraction of A) or "absolute"
  evidence TEXT,
  rule_version TEXT
);

CREATE TABLE IF NOT EXISTS locations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  latitude REAL NOT NULL,
  longitude REAL NOT NULL,
  boundary_id TEXT
);

CREATE TABLE IF NOT EXISTS environmental_features (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  location_id INTEGER NOT NULL REFERENCES locations(id),
  factor TEXT NOT NULL,
  value REAL,                     -- NULL means unknown
  unit TEXT,
  source TEXT,
  resolution TEXT,
  data_date TEXT,
  retrieved_at TEXT,
  transformation TEXT
);

CREATE TABLE IF NOT EXISTS assessments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  adaptation_id TEXT NOT NULL REFERENCES adaptations(id),
  location_a_id INTEGER NOT NULL REFERENCES locations(id),
  location_b_id INTEGER NOT NULL REFERENCES locations(id),
  status TEXT NOT NULL,
  score REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS assessment_factors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  assessment_id INTEGER NOT NULL REFERENCES assessments(id),
  factor TEXT NOT NULL,
  a_value REAL,
  b_value REAL,
  factor_status TEXT,             -- met / unmet / unknown / transfer_risk
  interpretation TEXT
);

CREATE TABLE IF NOT EXISTS geocoding_cache (
  query TEXT PRIMARY KEY,
  results_json TEXT NOT NULL,
  retrieved_at TEXT NOT NULL
);
