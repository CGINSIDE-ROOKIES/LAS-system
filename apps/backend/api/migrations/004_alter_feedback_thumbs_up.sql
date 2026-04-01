ALTER TABLE feedback
    DROP COLUMN rating,
    ADD COLUMN thumbs_up BOOLEAN NOT NULL;
