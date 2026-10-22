-- Drafts are isolated from published evidence and use a separate restricted login.
CREATE TABLE opslens.upload_drafts (
    id uuid PRIMARY KEY,
    owner text NOT NULL,
    filename text NOT NULL CHECK (length(filename) BETWEEN 1 AND 120),
    content text NOT NULL CHECK (octet_length(content) BETWEEN 1 AND 1000000),
    proposal jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX upload_drafts_owner_created ON opslens.upload_drafts(owner, created_at DESC);
ALTER TABLE opslens.upload_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE opslens.upload_drafts FORCE ROW LEVEL SECURITY;
CREATE POLICY draft_owner_read ON opslens.upload_drafts FOR SELECT TO opslens_draft_writer
    USING (owner = current_setting('opslens.draft_owner', true));
CREATE POLICY draft_owner_insert ON opslens.upload_drafts FOR INSERT TO opslens_draft_writer
    WITH CHECK (owner = current_setting('opslens.draft_owner', true));
REVOKE ALL ON opslens.upload_drafts FROM PUBLIC;
GRANT USAGE ON SCHEMA opslens TO opslens_draft_writer;
GRANT SELECT, INSERT ON opslens.upload_drafts TO opslens_draft_writer;
