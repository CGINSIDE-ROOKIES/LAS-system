DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'feedback_qa_id_unique'
          AND conrelid = 'feedback'::regclass
    ) THEN
        ALTER TABLE feedback ADD CONSTRAINT feedback_qa_id_unique UNIQUE (qa_id);
    END IF;
END $$;
