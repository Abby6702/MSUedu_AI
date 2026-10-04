USE msuedu_ai;

CREATE TABLE IF NOT EXISTS session_messages (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  request_id INT UNSIGNED NOT NULL,
  user_id    INT UNSIGNED NOT NULL,
  body       VARCHAR(1000) NOT NULL,
  created_at DATETIME NOT NULL,                   -- UTC
  PRIMARY KEY (id),
  KEY idx_sm_request (request_id, id),
  CONSTRAINT fk_sm_request FOREIGN KEY (request_id) REFERENCES tutoring_requests (id) ON DELETE CASCADE,
  CONSTRAINT fk_sm_user    FOREIGN KEY (user_id)    REFERENCES users (id)             ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;