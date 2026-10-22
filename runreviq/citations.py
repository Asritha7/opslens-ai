"""Validate manually reviewed claim quotations against exact source content."""
import hashlib


def validate_citations(claims, content):
    lines = content.splitlines()
    digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
    for claim in claims:
        if 'citation' not in claim:
            continue  # Legacy claims remain usable, explicitly uncited in responses.
        citation = claim['citation']
        if not isinstance(citation, dict) or set(citation) != {'start_line', 'end_line', 'quote', 'source_sha256'}:
            raise ValueError('Invalid claim citation fields')
        start, end = citation['start_line'], citation['end_line']
        if (type(start) is not int or type(end) is not int
                or not 1 <= start <= end <= len(lines)):
            raise ValueError('Invalid claim citation range')
        quote = citation['quote']
        if not isinstance(quote, str) or not quote.strip() or quote != '\n'.join(lines[start - 1:end]):
            raise ValueError('Claim quote does not match source lines')
        if citation['source_sha256'] != digest:
            raise ValueError('Claim citation source fingerprint is stale')
