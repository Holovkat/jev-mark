#!/usr/bin/env python3
"""Create a private, explicit retention checkpoint without editing session history."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

from compaction_retention import classify


def checkpoint(packet_path, output_path, base_url='http://127.0.0.1:8096'):
    packet_path, output_path = Path(packet_path), Path(output_path)
    if packet_path.resolve() == output_path.resolve():
        raise ValueError('The checkpoint output must differ from the source packet')
    raw = packet_path.read_bytes()
    result = classify(json.loads(raw), base_url)
    result['source'] = {'path': str(packet_path.resolve()),
                        'sha256': hashlib.sha256(raw).hexdigest()}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + output_path.name, dir=output_path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, output_path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base-url', default=os.environ.get('JEV_BASE_URL', 'http://127.0.0.1:8096'))
    args = parser.parse_args()
    try:
        result = checkpoint(args.packet, args.output, args.base_url)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Checkpoint could not be saved: {type(error).__name__}\n')
    print(json.dumps({'status': result['status'], 'output': str(args.output.resolve())}))
    return 0 if result['status'] == 'classified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
