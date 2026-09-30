USE msuedu_ai;

CREATE TABLE IF NOT EXISTS tutoring_requests (
  id                 INT UNSIGNED NOT NULL AUTO_INCREMENT,
  student_id         INT UNSIGNED NOT NULL,
  tutor_id           INT UNSIGNED NOT NULL,
  subject_id         INT UNSIGNED NOT NULL,
  topic              VARCHAR(150) NOT NULL,
  description        VARCHAR(1000) NULL,
  session_format     ENUM('online','in_person') NOT NULL,
  start_at           DATETIME NOT NULL,          -- stored in UTC
  end_at             DATETIME NOT NULL,          -- stored in UTC
  status             ENUM('pending','accepted','declined','reschedule_proposed',
                          'completed','cancelled') NOT NULL DEFAULT 'pending',
  proposed_start_at  DATETIME NULL,              -- UTC, only while a proposal is open
  proposed_end_at    DATETIME NULL,
  response_note      VARCHAR(500) NULL,
  created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_req_student (student_id, status),
  KEY idx_req_tutor (tutor_id, status),
  KEY idx_req_tutor_time (tutor_id, start_at, end_at),
  CONSTRAINT fk_req_student FOREIGN KEY (student_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_req_tutor   FOREIGN KEY (tutor_id)   REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_req_subject FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE RESTRICT,
  CONSTRAINT chk_req_times CHECK (end_at > start_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;