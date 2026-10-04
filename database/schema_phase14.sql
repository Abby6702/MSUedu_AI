USE msuedu_ai;

CREATE TABLE IF NOT EXISTS ai_conversations (
  id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id    INT UNSIGNED NOT NULL,
  title      VARCHAR(100) NOT NULL DEFAULT 'New conversation',
  subject_id INT UNSIGNED NULL,
  lesson_id  INT UNSIGNED NULL,
  created_at DATETIME NOT NULL,                 -- UTC
  updated_at DATETIME NOT NULL,                 -- UTC
  PRIMARY KEY (id),
  KEY idx_conv_user (user_id, updated_at),
  CONSTRAINT fk_conv_user    FOREIGN KEY (user_id)    REFERENCES users (id)    ON DELETE CASCADE,
  CONSTRAINT fk_conv_subject FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE SET NULL,
  CONSTRAINT fk_conv_lesson  FOREIGN KEY (lesson_id)  REFERENCES lessons (id)  ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ai_messages (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  conversation_id INT UNSIGNED NOT NULL,
  role            ENUM('user','assistant') NOT NULL,
  content         TEXT NOT NULL,
  created_at      DATETIME NOT NULL,            -- UTC
  PRIMARY KEY (id),
  KEY idx_msg_conv (conversation_id, id),
  CONSTRAINT fk_msg_conv FOREIGN KEY (conversation_id) REFERENCES ai_conversations (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;