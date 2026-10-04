USE msuedu_ai;

CREATE TABLE IF NOT EXISTS session_summaries (
  request_id     INT UNSIGNED NOT NULL,
  tutor_id       INT UNSIGNED NOT NULL,
  topics_covered VARCHAR(600) NOT NULL,
  strengths      VARCHAR(600) NULL,
  improvements   VARCHAR(600) NULL,
  practice       VARCHAR(600) NULL,
  next_lesson_id INT UNSIGNED NULL,
  status         ENUM('draft','approved') NOT NULL DEFAULT 'draft',
  ai_assisted    TINYINT(1) NOT NULL DEFAULT 0,
  created_at     DATETIME NOT NULL,                -- UTC
  updated_at     DATETIME NOT NULL,                -- UTC
  approved_at    DATETIME NULL,
  PRIMARY KEY (request_id),
  KEY idx_ss_status (status, approved_at),
  CONSTRAINT fk_ss_request FOREIGN KEY (request_id)     REFERENCES tutoring_requests (id) ON DELETE CASCADE,
  CONSTRAINT fk_ss_tutor   FOREIGN KEY (tutor_id)       REFERENCES users (id)             ON DELETE CASCADE,
  CONSTRAINT fk_ss_lesson  FOREIGN KEY (next_lesson_id) REFERENCES lessons (id)           ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;