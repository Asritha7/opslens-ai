# Validated claim citations

Claims may optionally carry a manually reviewed `citation` object alongside their `action` and `rule`. The first cited fixtures are RB-050 and RB-051, revision 2. Their original procedure text is unchanged.

A citation contains exactly these fields:

- `start_line` and `end_line`: positive integer, one-based, inclusive line range.
- `quote`: exact nonblank text from that range, with multiline quotes joined by `\n`.
- `source_sha256`: SHA-256 of the entire UTF-8 source content read by ingestion, before metadata is combined with it.

Ingestion validates the range, exact quotation, and fingerprint before starting the write transaction. Boolean line numbers, extra fields, empty quotes, out-of-range lines, mismatched text, and stale fingerprints are rejected. A change outside the quoted passage also changes the fingerprint and requires revalidation. Source files are read as UTF-8 text using Python's standard newline normalization; line comparisons use `splitlines()`.

Citation metadata is part of the immutable document version and its combined checksum. Adding or editing it requires a new revision even if the source text is unchanged. An unchanged repeat import is a no-op. Existing historical revisions remain available under current access policy. A fresh catalog import is not an archive of revisions absent from that catalog.

## Author and review

1. Choose the exact source lines that support the normalized action and must/must_not rule.
2. Verify the meaning and any conditions with the document owner; a matching quotation alone does not establish semantic support.
3. Copy those lines exactly and compute the content fingerprint using the same UTF-8 text representation as ingestion.
4. Add the citation to the claim and increment the document revision for an existing published document.
5. Ingest the reviewed catalog and inspect the authenticated conflict response.

The extractor does not automatically produce claims or citations. It also cannot approve documents or assign permissions. Line numbers are stable only within the cited revision; do not reuse them against the current file after edits.

## Reader behavior

Database selection validates citations against the stored content after row-level permission filtering. It does not read the current local source files. File-backed operator demonstrations validate cited catalog entries against their source files when loading the catalog. Pure `select()` expects already validated documents, like the database and file loaders supply.

The conflict response attaches the quote, lines, content hash, document ID, revision, and rule to each cited document. The existing authenticated revision endpoint retrieves the full corresponding content. Current access revocation blocks subsequent reads of old and new evidence; previously delivered text cannot be retracted.

Legacy claims without citations are supported and marked `citation_status: incomplete`. Conflict detection continues and recommendations remain withheld. No passage is invented to fill a missing citation. Validity means exact source correspondence, not model-based semantic verification. Quotes are untrusted document text and must be safely rendered by any future UI.

See [API response fields](api.md#conflict-source-citations), [setup](../SETUP.md#publish-and-inspect-conflict-citations), and [testing](testing.md).
