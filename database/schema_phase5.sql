USE msuedu_ai;

-- Metadata only. This table NEVER stores what students typed or what the AI answered.
CREATE TABLE IF NOT EXISTS ai_usage_logs (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id     INT UNSIGNED NULL,
  feature     VARCHAR(30) NOT NULL,          -- 'chat', 'summary' (later: 'quiz', 'agent')
  subject_id  INT UNSIGNED NULL,
  success     TINYINT(1) NOT NULL,
  error_code  VARCHAR(30) NULL,
  duration_ms INT UNSIGNED NULL,
  created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_ai_user_time (user_id, created_at),
  CONSTRAINT fk_ai_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL,
  CONSTRAINT fk_ai_subject FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;