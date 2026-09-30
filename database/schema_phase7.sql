USE msuedu_ai;

-- A "proposal" is something the agent PREPARED. It does nothing until the student confirms.
CREATE TABLE IF NOT EXISTS agent_proposals (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id     INT UNSIGNED NOT NULL,
  kind        ENUM('request','cancel') NOT NULL,
  payload     JSON NOT NULL,                 -- ids, times and display lines (not chat text)
  status      ENUM('prepared','confirmed','discarded','expired') NOT NULL DEFAULT 'prepared',
  created_at  DATETIME NOT NULL,             -- UTC
  expires_at  DATETIME NOT NULL,             -- UTC
  resolved_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY idx_prop_user_status (user_id, status),
  CONSTRAINT fk_prop_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- What the agent did, for debugging and accountability. Numeric ids only, never message text.
CREATE TABLE IF NOT EXISTS agent_action_logs (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_id     CHAR(16) NOT NULL,              -- groups the steps of one message
  user_id    INT UNSIGNED NULL,
  step       ENUM('plan','tool','confirm') NOT NULL,
  tool_name  VARCHAR(40) NULL,
  ok         TINYINT(1) NOT NULL,
  detail     VARCHAR(255) NULL,
  created_at DATETIME NOT NULL,              -- UTC
  PRIMARY KEY (id),
  KEY idx_agentlog_run (run_id),
  KEY idx_agentlog_user (user_id, created_at),
  CONSTRAINT fk_agentlog_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;