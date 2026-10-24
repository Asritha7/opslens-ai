CREATE TABLE opslens.document_withdrawals (
    document_id text NOT NULL,
    revision integer NOT NULL,
    actor text NOT NULL,
    reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 2000),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(document_id, revision),
    FOREIGN KEY(document_id, revision) REFERENCES opslens.document_versions(document_id, revision)
);
ALTER TABLE opslens.document_withdrawals ENABLE ROW LEVEL SECURITY;
ALTER TABLE opslens.document_withdrawals FORCE ROW LEVEL SECURITY;
CREATE POLICY withdrawal_publisher_read ON opslens.document_withdrawals FOR SELECT TO opslens_publish_operator USING (true);
CREATE POLICY withdrawal_publisher_insert ON opslens.document_withdrawals FOR INSERT TO opslens_publish_operator
    WITH CHECK (actor=current_setting('opslens.publisher',true) AND EXISTS (
        SELECT 1 FROM opslens.documents d WHERE d.id=document_id AND d.current_revision=revision));
CREATE POLICY withdrawal_reader_read ON opslens.document_withdrawals FOR SELECT
    TO opslens_reader_platform, opslens_reader_security, opslens_reader_intern
    USING (EXISTS (SELECT 1 FROM opslens.documents d WHERE d.id=document_id));
REVOKE ALL ON opslens.document_withdrawals FROM PUBLIC;
GRANT SELECT, INSERT ON opslens.document_withdrawals TO opslens_publish_operator;
GRANT SELECT(document_id,revision,reason,created_at) ON opslens.document_withdrawals
    TO opslens_reader_platform, opslens_reader_security, opslens_reader_intern;
