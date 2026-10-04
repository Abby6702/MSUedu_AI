USE msuedu_ai;

CREATE TABLE IF NOT EXISTS session_files (
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  request_id    INT UNSIGNED NOT NULL,
  user_id       INT UNSIGNED NOT NULL,              -- who uploaded it
  original_name VARCHAR(120) NOT NULL,              -- cleaned name shown to people
  stored_name   VARCHAR(40) NOT NULL,               -- random name on disk
  kind          VARCHAR(10) NOT NULL,               -- pdf, docx, pptx, jpeg, png, webp, gif, txt
  size_bytes    INT UNSIGNED NOT NULL,
  created_at    DATETIME NOT NULL,                  -- UTC
  PRIMARY KEY (id),
  UNIQUE KEY uq_sf_stored (stored_name),
  KEY idx_sf_request (request_id, id),
  CONSTRAINT fk_sf_request FOREIGN KEY (request_id) REFERENCES tutoring_requests (id) ON DELETE CASCADE,
  CONSTRAINT fk_sf_user    FOREIGN KEY (user_id)    REFERENCES users (id)             ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;