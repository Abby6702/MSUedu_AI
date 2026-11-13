USE msuedu_ai;

CREATE TABLE IF NOT EXISTS tutor_subject_requests (
  id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
  tutor_id        INT UNSIGNED NOT NULL,
  subject_name    VARCHAR(100) NOT NULL,
  category        VARCHAR(60) NULL,
  topics          VARCHAR(255) NULL,
  rate_30         INT UNSIGNED NOT NULL,
  rate_60         INT UNSIGNED NOT NULL,
  rate_90         INT UNSIGNED NOT NULL,
  rate_120        INT UNSIGNED NOT NULL,
  status          ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
  reviewed_by     INT UNSIGNED NULL,
  reviewed_at     TIMESTAMP NULL,
  created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_subject_request_status (status, created_at),
  KEY idx_subject_request_tutor (tutor_id, status),
  CONSTRAINT fk_subject_request_tutor FOREIGN KEY (tutor_id)
    REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_subject_request_reviewer FOREIGN KEY (reviewed_by)
    REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
