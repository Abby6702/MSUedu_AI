USE msuedu_ai;

CREATE TABLE IF NOT EXISTS quizzes (
  id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id        INT UNSIGNED NOT NULL,
  subject_id     INT UNSIGNED NULL,
  topic          VARCHAR(100) NOT NULL,
  difficulty     ENUM('easy','medium','hard') NOT NULL,
  mode           ENUM('practice','test') NOT NULL,
  question_count TINYINT UNSIGNED NOT NULL,
  created_at     DATETIME NOT NULL,                 -- UTC
  PRIMARY KEY (id),
  KEY idx_quiz_user (user_id, created_at),
  CONSTRAINT fk_quiz_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_quiz_subject FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS quiz_questions (
  id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
  quiz_id          INT UNSIGNED NOT NULL,
  position         TINYINT UNSIGNED NOT NULL,
  q_type           ENUM('mcq','tf','short') NOT NULL,
  question_text    VARCHAR(600) NOT NULL,
  options          JSON NULL,                       -- list of 4 texts, only for mcq
  correct_answer   VARCHAR(255) NOT NULL,           -- mcq: option index "0".."3"; tf: "true"/"false"; short: model answer
  accepted_answers JSON NULL,                       -- short answer: other accepted wordings
  explanation      VARCHAR(1000) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_question_position (quiz_id, position),
  CONSTRAINT fk_qq_quiz FOREIGN KEY (quiz_id) REFERENCES quizzes (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS quiz_attempts (
  id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
  quiz_id          INT UNSIGNED NOT NULL,
  user_id          INT UNSIGNED NOT NULL,
  score            TINYINT UNSIGNED NOT NULL,
  total            TINYINT UNSIGNED NOT NULL,
  answers_revealed TINYINT(1) NOT NULL DEFAULT 0,
  submitted_at     DATETIME NOT NULL,               -- UTC
  PRIMARY KEY (id),
  KEY idx_attempt_quiz (quiz_id, submitted_at),
  KEY idx_attempt_user (user_id, submitted_at),
  CONSTRAINT fk_att_quiz FOREIGN KEY (quiz_id) REFERENCES quizzes (id) ON DELETE CASCADE,
  CONSTRAINT fk_att_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS quiz_answers (
  attempt_id  INT UNSIGNED NOT NULL,
  question_id INT UNSIGNED NOT NULL,
  answer_text VARCHAR(500) NULL,
  is_correct  TINYINT(1) NOT NULL,
  PRIMARY KEY (attempt_id, question_id),
  CONSTRAINT fk_ans_attempt FOREIGN KEY (attempt_id) REFERENCES quiz_attempts (id) ON DELETE CASCADE,
  CONSTRAINT fk_ans_question FOREIGN KEY (question_id) REFERENCES quiz_questions (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;