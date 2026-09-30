USE msuedu_ai;

-- Failed logins only. Values are keyed hashes (HMAC), never raw emails or IPs.
CREATE TABLE IF NOT EXISTS login_attempts (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  identity_hash CHAR(64) NOT NULL,
  ip_hash       CHAR(64) NOT NULL,
  attempted_at  DATETIME NOT NULL,             -- UTC
  PRIMARY KEY (id),
  KEY idx_la_identity (identity_hash, attempted_at),
  KEY idx_la_ip (ip_hash, attempted_at),
  KEY idx_la_time (attempted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS platform_settings (
  setting_key   VARCHAR(40) NOT NULL,
  setting_value VARCHAR(500) NOT NULL,
  updated_by    INT UNSIGNED NULL,
  updated_at    DATETIME NOT NULL,             -- UTC
  PRIMARY KEY (setting_key),
  CONSTRAINT fk_setting_user FOREIGN KEY (updated_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO platform_settings (setting_key, setting_value, updated_at) VALUES
  ('announcement', '', UTC_TIMESTAMP()),
  ('registration_open', 'true', UTC_TIMESTAMP());

-- Keep this LAST. Run the script ONCE: a second run stops here with
-- "Duplicate column name", which is harmless (everything above already ran).
ALTER TABLE users
  ADD COLUMN must_change_password TINYINT(1) NOT NULL DEFAULT 0 AFTER is_active,
  ADD COLUMN session_version INT UNSIGNED NOT NULL DEFAULT 0 AFTER must_change_password;