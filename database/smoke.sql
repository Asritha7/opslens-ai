\set ON_ERROR_STOP on
SELECT current_database(), current_user;
SELECT extversion AS pgvector_version FROM pg_extension WHERE extname = 'vector';
BEGIN;
CREATE TEMP TABLE vector_smoke (label text, embedding vector(3));
INSERT INTO vector_smoke VALUES ('closest', '[1,0,0]'), ('farther', '[0,1,0]');
DO $$
DECLARE result text;
BEGIN
  SELECT label INTO result FROM vector_smoke ORDER BY embedding <-> '[0.9,0.1,0]' LIMIT 1;
  IF result IS DISTINCT FROM 'closest' THEN
    RAISE EXCEPTION 'Vector similarity check failed';
  END IF;
END $$;
SELECT label AS nearest_match FROM vector_smoke ORDER BY embedding <-> '[0.9,0.1,0]' LIMIT 1;
ROLLBACK;
