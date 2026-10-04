USE msuedu_ai;

-- Run this script ONCE. A second run stops with "Duplicate column name", which is harmless.
ALTER TABLE quizzes
  ADD COLUMN topic_id INT UNSIGNED NULL AFTER subject_id,
  ADD KEY idx_quiz_topic (topic_id),
  ADD CONSTRAINT fk_quiz_topic FOREIGN KEY (topic_id) REFERENCES topics (id) ON DELETE SET NULL;