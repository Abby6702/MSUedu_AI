USE msuedu_ai;

CREATE TABLE IF NOT EXISTS recommendations (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id     INT UNSIGNED NOT NULL,
  topic_id    INT UNSIGNED NULL,
  subject_id  INT UNSIGNED NULL,
  lesson_id   INT UNSIGNED NULL,
  kind        ENUM('review_lesson','practice','human_tutor','next_lesson') NOT NULL,
  difficulty  ENUM('easy','medium','hard') NULL,
  title       VARCHAR(200) NOT NULL,
  message     VARCHAR(500) NOT NULL,
  reasoning   JSON NOT NULL,                       -- {"rule": .., "facts": {..}, "steps": [..]}
  evidence    INT UNSIGNED NOT NULL DEFAULT 0,     -- quiz attempts + lessons done when it was made
  status      ENUM('active','dismissed','done','superseded') NOT NULL DEFAULT 'active',
  dedupe_key  VARCHAR(30) NULL,                    -- set while active or dismissed, NULL once closed
  created_at  DATETIME NOT NULL,                   -- UTC
  resolved_at DATETIME NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_rec_key (user_id, dedupe_key),     -- one live recommendation per topic or subject
  KEY idx_rec_user_status (user_id, status, created_at),
  CONSTRAINT fk_rec_user    FOREIGN KEY (user_id)    REFERENCES users (id)    ON DELETE CASCADE,
  CONSTRAINT fk_rec_topic   FOREIGN KEY (topic_id)   REFERENCES topics (id)   ON DELETE SET NULL,
  CONSTRAINT fk_rec_subject FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE SET NULL,
  CONSTRAINT fk_rec_lesson  FOREIGN KEY (lesson_id)  REFERENCES lessons (id)  ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;