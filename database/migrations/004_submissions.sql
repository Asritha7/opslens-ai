CREATE TABLE opslens.draft_submissions (
    id uuid PRIMARY KEY,
    draft_id uuid NOT NULL,
    revision integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (draft_id, revision),
    FOREIGN KEY (draft_id, revision) REFERENCES opslens.draft_reviews(draft_id, revision)
);
CREATE TABLE opslens.submission_decisions (
    submission_id uuid PRIMARY KEY REFERENCES opslens.draft_submissions(id),
    reviewer text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('approved', 'changes_requested')),
    comment text NOT NULL CHECK (length(comment) BETWEEN 1 AND 2000),
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE opslens.draft_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE opslens.draft_submissions FORCE ROW LEVEL SECURITY;
ALTER TABLE opslens.submission_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE opslens.submission_decisions FORCE ROW LEVEL SECURITY;
CREATE POLICY submission_owner_read ON opslens.draft_submissions FOR SELECT TO opslens_draft_writer
    USING (EXISTS (SELECT 1 FROM opslens.upload_drafts d WHERE d.id = draft_id));
CREATE POLICY submission_owner_insert ON opslens.draft_submissions FOR INSERT TO opslens_draft_writer
    WITH CHECK (EXISTS (SELECT 1 FROM opslens.upload_drafts d WHERE d.id = draft_id));
CREATE POLICY submission_reviewer_read ON opslens.draft_submissions FOR SELECT TO opslens_review_operator USING (true);
CREATE POLICY decision_owner_read ON opslens.submission_decisions FOR SELECT TO opslens_draft_writer
    USING (EXISTS (SELECT 1 FROM opslens.draft_submissions s WHERE s.id = submission_id));
CREATE POLICY decision_reviewer_read ON opslens.submission_decisions FOR SELECT TO opslens_review_operator USING (true);
CREATE POLICY decision_reviewer_insert ON opslens.submission_decisions FOR INSERT TO opslens_review_operator
    WITH CHECK (reviewer = current_setting('opslens.reviewer', true) AND EXISTS (
        SELECT 1 FROM opslens.draft_submissions s JOIN opslens.upload_drafts d ON d.id=s.draft_id
        WHERE s.id=submission_id AND d.owner <> reviewer));
-- Only submitted drafts/revisions become visible through the review account.
CREATE POLICY submitted_draft_read ON opslens.upload_drafts FOR SELECT TO opslens_review_operator
    USING (EXISTS (SELECT 1 FROM opslens.draft_submissions s WHERE s.draft_id=upload_drafts.id));
CREATE POLICY submitted_review_read ON opslens.draft_reviews FOR SELECT TO opslens_review_operator
    USING (EXISTS (SELECT 1 FROM opslens.draft_submissions s WHERE s.draft_id=draft_reviews.draft_id AND s.revision=draft_reviews.revision));
REVOKE ALL ON opslens.draft_submissions, opslens.submission_decisions FROM PUBLIC;
GRANT SELECT, INSERT ON opslens.draft_submissions TO opslens_draft_writer;
GRANT SELECT ON opslens.submission_decisions TO opslens_draft_writer;
GRANT USAGE ON SCHEMA opslens TO opslens_review_operator;
GRANT SELECT ON opslens.draft_submissions, opslens.submission_decisions, opslens.upload_drafts, opslens.draft_reviews TO opslens_review_operator;
GRANT INSERT ON opslens.submission_decisions TO opslens_review_operator;
