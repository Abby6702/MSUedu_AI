USE msuedu_ai;

CREATE TABLE IF NOT EXISTS notifications (
  id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id    INT UNSIGNED NOT NULL,
  kind       VARCHAR(30) NOT NULL,
  title      VARCHAR(150) NOT NULL,
  body       VARCHAR(500) NOT NULL,
  link       VARCHAR(200) NULL,                 -- an internal path such as /student/requests
  dedupe_key VARCHAR(80) NOT NULL,              -- same event = same key = saved only once
  is_read    TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL,                 -- UTC
  PRIMARY KEY (id),
  UNIQUE KEY uq_notif_dedupe (user_id, dedupe_key),
  KEY idx_notif_user (user_id, is_read, created_at),
  CONSTRAINT fk_notif_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS notification_preferences (
  user_id           INT UNSIGNED NOT NULL,
  reminders_enabled TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (user_id),
  CONSTRAINT fk_pref_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS feedback (
  id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  request_id INT UNSIGNED NOT NULL,
  student_id INT UNSIGNED NOT NULL,
  tutor_id   INT UNSIGNED NOT NULL,
  rating     TINYINT UNSIGNED NOT NULL,
  comment    VARCHAR(1000) NULL,
  is_hidden  TINYINT(1) NOT NULL DEFAULT 0,     -- for moderation (admin screen in Phase 9)
  created_at DATETIME NOT NULL,                 -- UTC
  PRIMARY KEY (id),
  UNIQUE KEY uq_feedback_request (request_id),  -- one feedback per session
  KEY idx_feedback_tutor (tutor_id, is_hidden, created_at),
  CONSTRAINT fk_fb_request FOREIGN KEY (request_id) REFERENCES tutoring_requests (id) ON DELETE CASCADE,
  CONSTRAINT fk_fb_student FOREIGN KEY (student_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_fb_tutor   FOREIGN KEY (tutor_id)   REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT chk_fb_rating CHECK (rating BETWEEN 1 AND 5)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS session_records (
  request_id          INT UNSIGNED NOT NULL,
  tutor_id            INT UNSIGNED NOT NULL,
  topics_covered      VARCHAR(500) NOT NULL,
  outcomes            VARCHAR(1000) NOT NULL,
  next_steps          VARCHAR(500) NULL,
  summary_text        VARCHAR(1500) NULL,       -- tutor-approved recap
  summary_ai_assisted TINYINT(1) NOT NULL DEFAULT 0,
  updated_at          DATETIME NOT NULL,        -- UTC
  PRIMARY KEY (request_id),
  CONSTRAINT fk_rec_request FOREIGN KEY (request_id) REFERENCES tutoring_requests (id) ON DELETE CASCADE,
  CONSTRAINT fk_rec_tutor   FOREIGN KEY (tutor_id)   REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;