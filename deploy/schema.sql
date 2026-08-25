-- MacroRSS MySQL 8+ schema. Run as an administrative account once.
-- Application credentials are NEVER stored in this repository.
CREATE DATABASE IF NOT EXISTS macrorss
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
USE macrorss;

CREATE TABLE IF NOT EXISTS schema_meta (
  schema_version INT NOT NULL PRIMARY KEY,
  applied_at DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6))
) ENGINE=InnoDB;

INSERT INTO schema_meta (schema_version)
VALUES (1)
ON DUPLICATE KEY UPDATE applied_at = applied_at;

CREATE TABLE IF NOT EXISTS raw_items (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_id VARCHAR(128) NOT NULL,
  guid_hash BINARY(32) NOT NULL,
  guid TEXT NULL,
  url TEXT NULL,
  title TEXT NOT NULL,
  raw_published_at VARCHAR(255) NULL,
  published_at DATETIME(6) NULL,
  first_seen_at DATETIME(6) NOT NULL,
  payload_json JSON NULL,
  created_at DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
  PRIMARY KEY (id),
  UNIQUE KEY uq_raw_source_guid (source_id, guid_hash),
  KEY ix_raw_first_seen (first_seen_at),
  KEY ix_raw_published (published_at),
  KEY ix_raw_source_seen (source_id, first_seen_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_fingerprint BINARY(32) NOT NULL,
  canonical_url TEXT NULL,
  canonical_title TEXT NOT NULL,
  institution VARCHAR(128) NOT NULL,
  event_type VARCHAR(64) NOT NULL,
  published_at DATETIME(6) NULL,
  first_seen_at DATETIME(6) NOT NULL,
  first_source_id VARCHAR(128) NOT NULL,
  tags_json JSON NOT NULL,
  rank_gold SMALLINT UNSIGNED NULL,
  rank_fx SMALLINT UNSIGNED NULL,
  first_emitted_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
  PRIMARY KEY (id),
  UNIQUE KEY uq_event_fingerprint (event_fingerprint),
  KEY ix_events_seen (first_seen_at),
  KEY ix_events_type_seen (event_type, first_seen_at),
  KEY ix_events_institution_seen (institution, first_seen_at),
  KEY ix_events_gold_seen (rank_gold, first_seen_at),
  KEY ix_events_fx_seen (rank_fx, first_seen_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS event_observations (
  event_id BIGINT UNSIGNED NOT NULL,
  raw_item_id BIGINT UNSIGNED NOT NULL,
  observed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (event_id, raw_item_id),
  UNIQUE KEY uq_observation_raw (raw_item_id),
  KEY ix_observation_seen (observed_at),
  CONSTRAINT fk_observation_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
  CONSTRAINT fk_observation_raw FOREIGN KEY (raw_item_id) REFERENCES raw_items(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS feed_state (
  source_id VARCHAR(128) NOT NULL,
  etag TEXT NULL,
  last_modified TEXT NULL,
  last_success_at DATETIME(6) NULL,
  last_attempt_at DATETIME(6) NULL,
  consecutive_errors INT UNSIGNED NOT NULL DEFAULT 0,
  last_status SMALLINT UNSIGNED NULL,
  updated_at DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)) ON UPDATE UTC_TIMESTAMP(6),
  PRIMARY KEY (source_id),
  KEY ix_feed_state_success (last_success_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS deliveries (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_id BIGINT UNSIGNED NOT NULL,
  sink VARCHAR(64) NOT NULL,
  delivered_at DATETIME(6) NULL,
  attempts INT UNSIGNED NOT NULL DEFAULT 0,
  last_error TEXT NULL,
  updated_at DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)) ON UPDATE UTC_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_delivery_event_sink (event_id, sink),
  KEY ix_delivery_pending (sink, delivered_at),
  CONSTRAINT fk_delivery_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
