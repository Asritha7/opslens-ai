"""Local operator demo client: reads a key from disk without exposing it in argv."""
import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from runreviq.api import KEY_FILE, read_keys
from runreviq.selector import ROLES


def main():
    parser = argparse.ArgumentParser(description='Query the local API using a stored demo credential')
    parser.add_argument('--persona', required=True, choices=sorted(ROLES))
    parser.add_argument('--version', required=True)
    parser.add_argument('--environment', required=True, choices=['production', 'staging'])
    parser.add_argument('--key-rotation', choices=['true', 'false', 'unknown'], default='unknown')
    args = parser.parse_args()
    try:
        record = next(r for r in read_keys(KEY_FILE) if r['subject'] == f'demo-{args.persona}')
        body = json.dumps(dict(service='identity-service', software_version=args.version,
                               environment=args.environment,
                               key_rotation_enabled={'true': True, 'false': False, 'unknown': None}[args.key_rotation])).encode()
        request = Request('http://127.0.0.1:8000/v1/select', data=body,
                          headers={'Authorization': f"Bearer {record['token']}", 'Content-Type': 'application/json'})
        with urlopen(request, timeout=10) as response:
            print(json.dumps(json.load(response), indent=2))
    except HTTPError as exc:
        parser.exit(1, f'API request rejected (HTTP {exc.code}).\n')
    except (OSError, ValueError, StopIteration, URLError):
        parser.exit(1, 'Local API or demo credential unavailable; see SETUP.md.\n')


if __name__ == '__main__':
    main()
