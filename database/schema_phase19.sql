USE msuedu_ai;

ALTER TABLE tutor_profiles
  ADD COLUMN payment_method ENUM('gcash','maya','bank_transfer') NULL;

ALTER TABLE tutor_profiles
  ADD COLUMN payment_account_name VARCHAR(100) NULL;

ALTER TABLE tutor_profiles
  ADD COLUMN payment_account_number VARCHAR(50) NULL;

ALTER TABLE tutor_subjects
  ADD COLUMN rate_30 INT UNSIGNED NOT NULL DEFAULT 0;

ALTER TABLE tutor_subjects
  ADD COLUMN rate_60 INT UNSIGNED NOT NULL DEFAULT 0;

ALTER TABLE tutor_subjects
  ADD COLUMN rate_90 INT UNSIGNED NOT NULL DEFAULT 0;

ALTER TABLE tutor_subjects
  ADD COLUMN rate_120 INT UNSIGNED NOT NULL DEFAULT 0;

ALTER TABLE tutoring_requests
  ADD COLUMN payment_amount INT UNSIGNED NOT NULL DEFAULT 0;

ALTER TABLE tutoring_requests
  ADD COLUMN payment_method ENUM('gcash','maya','bank_transfer') NULL;

ALTER TABLE tutoring_requests
  ADD COLUMN payment_status ENUM('unpaid','submitted','verified','rejected')
  NOT NULL DEFAULT 'unpaid';

ALTER TABLE tutoring_requests
  ADD COLUMN payment_proof_path VARCHAR(100) NULL;
