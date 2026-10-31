-- Public HUD projection v1. Producer alone creates/migrates/writes these tables.
CREATE TABLE hud_public_meta (
  singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
  schema_version TEXT NOT NULL CHECK(schema_version = 'd4planner-hud-db/v1'),
  db_id TEXT NOT NULL,
  epoch TEXT NOT NULL
);
CREATE TABLE hud_current (
  singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
  hud_revision INTEGER NOT NULL CHECK(hud_revision >= 0),
  payload_json TEXT NOT NULL
);
