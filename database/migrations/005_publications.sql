CREATE TABLE opslens.publications (
    submission_id uuid PRIMARY KEY REFERENCES opslens.draft_submissions(id),
    document_id text NOT NULL,
    revision integer NOT NULL,
    publisher text NOT NULL,
    allowed_roles text[] NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(document_id, revision),
    FOREIGN KEY(document_id, revision) REFERENCES opslens.document_versions(document_id, revision)
);
ALTER TABLE opslens.publications ENABLE ROW LEVEL SECURITY;
ALTER TABLE opslens.publications FORCE ROW LEVEL SECURITY;
CREATE POLICY publication_owner_read ON opslens.publications FOR SELECT TO opslens_draft_writer
    USING (EXISTS (SELECT 1 FROM opslens.draft_submissions s WHERE s.id=submission_id));
CREATE POLICY publication_operator_read ON opslens.publications FOR SELECT TO opslens_publish_operator USING (true);
CREATE POLICY publication_operator_insert ON opslens.publications FOR INSERT TO opslens_publish_operator
    WITH CHECK (publisher=current_setting('opslens.publisher',true) AND EXISTS (
        SELECT 1 FROM opslens.submission_decisions d WHERE d.submission_id=publications.submission_id AND d.decision='approved'));
CREATE POLICY publisher_submissions ON opslens.draft_submissions FOR SELECT TO opslens_publish_operator
    USING (EXISTS (SELECT 1 FROM opslens.submission_decisions d WHERE d.submission_id=draft_submissions.id AND d.decision='approved'));
CREATE POLICY publisher_decisions ON opslens.submission_decisions FOR SELECT TO opslens_publish_operator USING (decision='approved');
CREATE POLICY publisher_drafts ON opslens.upload_drafts FOR SELECT TO opslens_publish_operator
    USING (EXISTS (SELECT 1 FROM opslens.draft_submissions s WHERE s.draft_id=upload_drafts.id));
CREATE POLICY publisher_reviews ON opslens.draft_reviews FOR SELECT TO opslens_publish_operator
    USING (EXISTS (SELECT 1 FROM opslens.draft_submissions s WHERE s.draft_id=draft_reviews.draft_id AND s.revision=draft_reviews.revision));
CREATE POLICY publisher_documents ON opslens.documents FOR ALL TO opslens_publish_operator USING (true) WITH CHECK (true);
CREATE POLICY publisher_versions ON opslens.document_versions FOR INSERT TO opslens_publish_operator WITH CHECK (true);
GRANT USAGE ON SCHEMA opslens TO opslens_publish_operator;
GRANT SELECT ON opslens.draft_submissions,opslens.submission_decisions,opslens.upload_drafts,opslens.draft_reviews,opslens.documents,opslens.document_versions,opslens.publications TO opslens_publish_operator;
GRANT INSERT ON opslens.documents,opslens.document_versions,opslens.publications TO opslens_publish_operator;
GRANT UPDATE(current_revision,allowed_roles) ON opslens.documents TO opslens_publish_operator;
GRANT SELECT ON opslens.publications TO opslens_draft_writer;
REVOKE ALL ON opslens.publications FROM PUBLIC;
CREATE POLICY publication_reviewer_read ON opslens.publications FOR SELECT TO opslens_review_operator USING (true);
GRANT SELECT(submission_id) ON opslens.publications TO opslens_review_operator;
