USE msuedu_ai;

-- Run each ALTER once. "Duplicate column name" means that one already ran (harmless).
ALTER TABLE tutor_profiles
  ADD COLUMN skills VARCHAR(500) NULL AFTER bio,
  ADD COLUMN education VARCHAR(300) NULL AFTER skills,
  ADD COLUMN experience VARCHAR(1000) NULL AFTER education,
  ADD COLUMN photo_filename VARCHAR(80) NULL AFTER experience;

ALTER TABLE student_profiles
  ADD COLUMN share_progress_with_tutors TINYINT(1) NOT NULL DEFAULT 0 AFTER learning_goals;