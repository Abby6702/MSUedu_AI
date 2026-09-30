USE msuedu_ai;

-- New column on tutor_profiles. Run this script ONCE:
-- running it a second time gives "Duplicate column name", which is harmless.
ALTER TABLE tutor_profiles
  ADD COLUMN tutoring_format ENUM('online','in_person','both') NOT NULL DEFAULT 'both'
  AFTER bio;

CREATE TABLE IF NOT EXISTS subjects (
  id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name       VARCHAR(100) NOT NULL,
  category   VARCHAR(60) NULL,
  is_active  TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_subject_name (name),
  KEY idx_subject_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tutor_subjects (
  tutor_id   INT UNSIGNED NOT NULL,
  subject_id INT UNSIGNED NOT NULL,
  topics     VARCHAR(255) NULL,
  PRIMARY KEY (tutor_id, subject_id),
  KEY idx_ts_subject (subject_id),
  CONSTRAINT fk_ts_tutor FOREIGN KEY (tutor_id)
    REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_ts_subject FOREIGN KEY (subject_id)
    REFERENCES subjects (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tutor_availability (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  tutor_id    INT UNSIGNED NOT NULL,
  day_of_week TINYINT UNSIGNED NOT NULL,      -- 0 = Monday ... 6 = Sunday
  start_time  TIME NOT NULL,                  -- Philippine local time
  end_time    TIME NOT NULL,
  created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_avail_tutor_day (tutor_id, day_of_week),
  KEY idx_avail_day (day_of_week),
  CONSTRAINT fk_avail_tutor FOREIGN KEY (tutor_id)
    REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT chk_avail_times CHECK (end_time > start_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Starter subject list. It is only a starting point: an admin can add,
-- deactivate or rename subjects later.
INSERT IGNORE INTO subjects (name, category) VALUES
  ('College Algebra', 'Mathematics'),
  ('Calculus 1', 'Mathematics'),
  ('Statistics', 'Mathematics'),
  ('General Physics', 'Science'),
  ('General Chemistry', 'Science'),
  ('Programming Fundamentals', 'Computing'),
  ('Data Structures', 'Computing'),
  ('English Composition', 'Languages');