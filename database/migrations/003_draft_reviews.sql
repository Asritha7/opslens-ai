-- Append-only review snapshots preserve original source and extraction.
CREATE TABLE opslens.draft_reviews (
    draft_id uuid NOT NULL REFERENCES opslens.upload_drafts(id),
    revision integer NOT NULL CHECK (revision BETWEEN 1 AND 100),
    metadata jsonb NOT NULL CHECK (octet_length(metadata::text) <= 10000),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (draft_id, revision)
);
ALTER TABLE opslens.draft_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE opslens.draft_reviews FORCE ROW LEVEL SECURITY;
CREATE POLICY review_owner_read ON opslens.draft_reviews FOR SELECT TO opslens_draft_writer
    USING (EXISTS (SELECT 1 FROM opslens.upload_drafts d WHERE d.id = draft_id));
CREATE POLICY review_owner_insert ON opslens.draft_reviews FOR INSERT TO opslens_draft_writer
    WITH CHECK (EXISTS (SELECT 1 FROM opslens.upload_drafts d WHERE d.id = draft_id));
REVOKE ALL ON opslens.draft_reviews FROM PUBLIC;
GRANT SELECT, INSERT ON opslens.draft_reviews TO opslens_draft_writer;
