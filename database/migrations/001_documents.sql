CREATE SCHEMA opslens;

CREATE TABLE opslens.documents (
    id text PRIMARY KEY,
    current_revision integer NOT NULL CHECK (current_revision > 0),
    allowed_roles text[] NOT NULL CHECK (allowed_roles <@ ARRAY['platform','security','intern']::text[])
);

CREATE TABLE opslens.document_versions (
    document_id text NOT NULL REFERENCES opslens.documents(id),
    revision integer NOT NULL CHECK (revision > 0),
    checksum text NOT NULL,
    metadata jsonb NOT NULL,
    content text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, revision)
);

ALTER TABLE opslens.documents ADD CONSTRAINT current_version_exists
    FOREIGN KEY (id, current_revision)
    REFERENCES opslens.document_versions(document_id, revision)
    DEFERRABLE INITIALLY DEFERRED;

CREATE FUNCTION opslens.reject_version_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Document versions are immutable; insert a new revision';
END;
$$;
CREATE TRIGGER immutable_version BEFORE UPDATE OR DELETE ON opslens.document_versions
    FOR EACH ROW EXECUTE FUNCTION opslens.reject_version_change();

ALTER TABLE opslens.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE opslens.documents FORCE ROW LEVEL SECURITY;
CREATE POLICY reader_documents ON opslens.documents FOR SELECT
    USING (EXISTS (SELECT 1 FROM unnest(allowed_roles) AS role_name
                  WHERE current_user::text = 'opslens_reader_' || role_name));

ALTER TABLE opslens.document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE opslens.document_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY reader_versions ON opslens.document_versions FOR SELECT
    USING (EXISTS (SELECT 1 FROM opslens.documents d WHERE d.id = document_id));

REVOKE ALL ON SCHEMA opslens FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA opslens FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA opslens FROM PUBLIC;
GRANT USAGE ON SCHEMA opslens TO opslens_reader_platform, opslens_reader_security, opslens_reader_intern;
GRANT SELECT ON ALL TABLES IN SCHEMA opslens TO opslens_reader_platform, opslens_reader_security, opslens_reader_intern;
