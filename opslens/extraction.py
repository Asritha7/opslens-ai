"""Extract reviewable metadata from explicit Markdown applicability fields."""
import argparse
import hashlib
import json
import re
from pathlib import Path

from opslens.selector import version

FIELDS = ('service', 'environment', 'version_min', 'version_max_exclusive', 'key_rotation_enabled')


def parse_value(field, raw):
    if field == 'service':
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', raw):
            raise ValueError('Use an explicit service identifier')
        return raw
    if field == 'environment':
        if raw not in ('production', 'staging'):
            raise ValueError('Use production or staging')
        return raw
    if field.startswith('version_'):
        if len(raw) > 32:
            raise ValueError('Version is too long')
        version(raw)
        return raw
    if raw not in ('true', 'false', 'none'):
        raise ValueError('Use true, false, or none (no requirement)')
    return {'true': True, 'false': False, 'none': None}[raw]


def extract(text):
    """Never reads permissions/catalog or grants approval; source text is only data."""
    encoded = text.encode('utf-8')
    if len(encoded) > 1_000_000:
        raise ValueError('Document exceeds 1 MB limit')
    candidates = {field: [] for field in FIELDS}
    title_candidates = []
    active = False
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        marker = re.match(r'^(`{3,}|~{3,})', stripped)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            continue
        if fence:
            continue
        if line.startswith('# '):
            title_candidates.append({'value': line[2:].strip(), 'line': number, 'quote': line})
        if re.match(r'^#{1,2}\s', line):
            active = line.strip() == '## Applicability'
            continue
        if not active:
            continue
        match = re.fullmatch(r'\s*(?:- )?([a-z_]+):\s*(.*?)\s*', line)
        if match and match[1] in FIELDS:
            candidates[match[1]].append({'raw': match[2], 'line': number, 'quote': line})

    metadata = {}
    provenance = {}
    issues = []
    if len(title_candidates) == 1 and title_candidates[0]['value']:
        metadata['title'] = title_candidates[0]['value']
        provenance['title'] = [title_candidates[0]]
    else:
        issues.append({'field': 'title', 'reason': 'missing_or_ambiguous'})
    for field, entries in candidates.items():
        provenance[field] = entries
        if len(entries) != 1:
            issues.append({'field': field, 'reason': 'missing' if not entries else 'ambiguous'})
            continue
        try:
            metadata[field] = parse_value(field, entries[0]['raw'])
        except ValueError:
            issues.append({'field': field, 'reason': 'invalid_value'})
    if ('version_min' in metadata and 'version_max_exclusive' in metadata
            and version(metadata['version_min']) >= version(metadata['version_max_exclusive'])):
        del metadata['version_min'], metadata['version_max_exclusive']
        issues.append({'field': 'version_range', 'reason': 'empty_or_inverted'})
    return {'schema_version': 1, 'extractor': 'explicit-markdown-v1',
            'source_sha256': hashlib.sha256(encoded).hexdigest(),
            'review_required': True, 'proposed_metadata': metadata,
            'provenance': provenance, 'issues': issues}


def main():
    parser = argparse.ArgumentParser(description='Propose metadata from a local Markdown document; never publishes it')
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    try:
        if args.source.suffix != '.md':
            raise ValueError('Expected Markdown')
        with args.source.open('rb') as stream:
            data = stream.read(1_000_001)
        if len(data) > 1_000_000:
            raise ValueError('Document too large')
        result = extract(data.decode('utf-8'))
    except (OSError, ValueError):
        parser.exit(1, 'Cannot extract: expected a readable UTF-8 Markdown file of at most 1 MB.\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
