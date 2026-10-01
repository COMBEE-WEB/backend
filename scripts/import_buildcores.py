"""Validate all OpenDB files, then optionally upsert public.parts. No deletes."""
import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import time
import tarfile
from uuid import UUID

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = {
    'CPU': 'cpu', 'CPUCooler': 'cpu_cooler', 'GPU': 'gpu', 'RAM': 'memory',
    'Storage': 'storage', 'Motherboard': 'motherboard', 'PSU': 'power_supply', 'PCCase': 'case',
    'Accessory': 'accessory', 'CaptureCard': 'capture_card', 'CaseFan': 'case_fan',
    'Chair': 'chair', 'Desk': 'desk', 'Headphones': 'headphones', 'Keyboard': 'keyboard',
    'Laptop': 'laptop', 'Lighting': 'lighting', 'Microphone': 'microphone', 'Monitor': 'monitor',
    'Mouse': 'mouse', 'Mousepad': 'mousepad', 'NetworkCard': 'network_card', 'OS': 'os',
    'PrebuiltDesktop': 'prebuilt_desktop', 'SoundCard': 'sound_card', 'Speaker': 'speaker',
    'Stand': 'stand', 'ThermalCompound': 'thermal_compound', 'VRHeadset': 'vr_headset', 'Webcam': 'webcam',
}


def git(repo, *args):
    return subprocess.check_output(['git', '-c', f'safe.directory={repo.as_posix()}', '-C', str(repo), *args], text=True).strip()


def transform(data, category, filename, commit, timestamp):
    if category not in CATEGORIES:
        raise ValueError(f'Unmapped category: {category}')
    source_id = str(UUID(data['opendb_id']))
    if source_id != filename:
        raise ValueError(f'ID does not match filename: {category}/{filename}')
    metadata = data.get('metadata') or {}
    warnings = []

    def field(value, limit, fallback=None, label='field'):
        if not isinstance(value, str) or not value.strip():
            value = fallback
            if fallback is not None:
                warnings.append(f'{label}: fallback')
        if value is None:
            return None
        value = value.strip()
        if len(value) > limit:
            warnings.append(f'{label}: shortened; original retained in specs')
        return value[:limit]

    row = {
        'external_id': 'buildcores:' + category + ':' + source_id,
        'category': CATEGORIES[category],
        'name': field(metadata.get('name') or data.get('name'), 200, f'{category} {source_id}', 'name'),
        'manufacturer': field(metadata.get('manufacturer') or data.get('manufacturer'), 100, 'Unknown', 'manufacturer'),
        'model_name': field(metadata.get('variant'), 150, label='model_name'),
        'source_url': f'https://github.com/buildcores/buildcores-open-db/blob/{commit}/open-db/{category}/{filename}.json',
        'source_updated_at': timestamp,
        'specs': data,
    }
    # Do not overwrite locally curated prices, images, descriptions or active status.
    return row, warnings


def prepare(repo, output):
    commit = git(repo, 'rev-parse', 'HEAD')
    timestamp = git(repo, 'show', '-s', '--format=%cI', 'HEAD')
    files = sorted((repo / 'open-db').glob('*/*.json'))
    tracked = git(repo, 'ls-tree', '-r', '--name-only', 'HEAD', 'open-db').splitlines()
    expected = {name for name in tracked if name.endswith('.json')}
    actual = {path.relative_to(repo).as_posix() for path in files}
    if expected != actual:
        raise ValueError('Source checkout incomplete or contains unexpected JSON files')
    if git(repo, 'status', '--porcelain', '--', 'open-db'):
        raise ValueError('Source data has local changes; use an unmodified snapshot')
    # Read the immutable Git snapshot in one stream, avoiding tens of thousands
    # of separate Windows file reads.
    archive_bytes = subprocess.check_output(['git', '-c', f'safe.directory={repo.as_posix()}', '-C', str(repo), 'archive', 'HEAD', 'open-db'])
    archive = tarfile.open(fileobj=io.BytesIO(archive_bytes), mode='r:')
    members = {member.name: member for member in archive.getmembers() if member.isfile()}
    output.mkdir(parents=True, exist_ok=True)
    report = {'source_commit': commit, 'source_snapshot_time': timestamp,
              'source_files': len(files), 'categories': {}, 'warnings': [], 'errors': []}
    counts, seen = Counter(), set()
    target = output / 'parts.jsonl'
    with target.open('w', encoding='utf-8', newline='\n') as stream:
        for path in files:
            try:
                data = json.loads(archive.extractfile(members[path.relative_to(repo).as_posix()]).read())
                row, warnings = transform(data, path.parent.name, path.stem, commit, timestamp)
                if row['external_id'] in seen:
                    raise ValueError(f'Duplicate ID: {row["external_id"]}')
                seen.add(row['external_id'])
                encoded = json.dumps(row, ensure_ascii=False, allow_nan=False)
                if '\\u0000' in encoded:
                    raise ValueError('PostgreSQL JSONB cannot contain NUL')
                stream.write(encoded + '\n')
                counts[row['category']] += 1
                if warnings:
                    report['warnings'].append({'file': path.relative_to(repo).as_posix(), 'details': warnings})
            except (ValueError, KeyError, TypeError) as error:
                report['errors'].append({'file': path.relative_to(repo).as_posix(), 'error': str(error)})
    report['categories'] = dict(sorted(counts.items()))
    report['prepared_rows'] = sum(counts.values())
    report['prepared_bytes'] = target.stat().st_size
    report['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in ('warnings', 'errors')}, ensure_ascii=False), flush=True)
    print(f'Warnings: {len(report["warnings"])}; errors: {len(report["errors"])}', flush=True)
    if report['errors'] or not seen:
        raise ValueError('Validation failed. See report.json; nothing uploaded.')
    return target, report


def request(client, method, url, **kwargs):
    for attempt in range(5):
        try:
            response = client.request(method, url, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError):
            if attempt == 4:
                raise RuntimeError('Network request failed; rerun safely to resume') from None
            time.sleep(2 ** attempt)
            continue
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 4:
            time.sleep(2 ** attempt)
            continue
        if response.is_error:
            try:
                code = response.json().get('code', 'unknown')
            except ValueError:
                code = 'unknown'
            raise RuntimeError(f'Supabase HTTP {response.status_code}, code={code}; upload stopped')
        return response


def upload(target, report, batch_size):
    load_dotenv(ROOT / '.env')
    url = os.getenv('SUPABASE_URL', '').rstrip('/')
    key = os.getenv('SUPABASE_SECRET_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url.startswith('https://') or not key:
        raise ValueError('Set SUPABASE_URL and SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY) in backend/.env')
    headers = {'apikey': key, 'Prefer': 'resolution=merge-duplicates,return=minimal'}
    if not key.startswith('sb_secret_'):
        headers['Authorization'] = 'Bearer ' + key
    with httpx.Client(headers=headers, timeout=60) as client:
        # A zero-row query validates every enum label before the first write.
        for category in report['categories']:
            request(client, 'GET', url + '/rest/v1/parts', params={'select': 'id', 'category': 'eq.' + category, 'limit': '0'})
        batch, written = [], 0
        with target.open(encoding='utf-8') as stream:
            for line in stream:
                batch.append(json.loads(line))
                if len(batch) == batch_size:
                    request(client, 'POST', url + '/rest/v1/parts', params={'on_conflict': 'external_id'}, json=batch)
                    written += len(batch)
                    print(f'Upserted {written}/{report["prepared_rows"]}', flush=True)
                    batch = []
            if batch:
                request(client, 'POST', url + '/rest/v1/parts', params={'on_conflict': 'external_id'}, json=batch)
                written += len(batch)
        # Compare every expected source ID against persisted IDs, including inactive rows.
        actual, offset = set(), 0
        while True:
            rows = request(client, 'GET', url + '/rest/v1/parts', params={
                'select': 'external_id', 'external_id': 'like.buildcores:*',
                'order': 'id.asc', 'offset': str(offset), 'limit': '1000',
            }).json()
            if not rows:
                break
            actual.update(row['external_id'] for row in rows)
            offset += len(rows)
        with target.open(encoding='utf-8') as stream:
            expected = {json.loads(line)['external_id'] for line in stream}
        missing = expected - actual
        result = {'source_commit': report['source_commit'], 'upserted': written,
                  'verified_ids': len(expected & actual), 'missing_ids': sorted(missing)}
        (target.parent / 'upload-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        if missing:
            raise RuntimeError(f'{len(missing)} imported IDs missing; see upload-result.json')
        print(f'COMPLETE: {written} rows upserted, all source IDs verified', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT.parent / 'buildcores-open-db')
    parser.add_argument('--output', type=Path, default=ROOT / 'import-output')
    parser.add_argument('--apply', action='store_true', help='Write validated data to Supabase')
    parser.add_argument('--prepared', action='store_true', help='Reuse a completed, checksum-verified dry run')
    parser.add_argument('--batch-size', type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 500:
        parser.error('batch-size must be between 1 and 500')
    if args.prepared:
        target = args.output.resolve() / 'parts.jsonl'
        report = json.loads((target.parent / 'report.json').read_text(encoding='utf-8'))
        if report['errors'] or not report['prepared_rows'] or report['prepared_rows'] != report['source_files']:
            raise ValueError('Prepared report is incomplete or has validation errors')
        if hashlib.sha256(target.read_bytes()).hexdigest() != report['sha256']:
            raise ValueError('Prepared data changed since validation; run a new dry run')
    else:
        target, report = prepare(args.source.resolve(), args.output.resolve())
    if args.apply:
        upload(target, report, args.batch_size)
    else:
        print('Dry run only. Apply the category migration, configure the admin key, then run with --apply.')


if __name__ == '__main__':
    main()
