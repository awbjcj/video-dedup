"""Versioned, atomic local scan and review history."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
import uuid
from pathlib import Path


def timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def new_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-' + uuid.uuid4().hex[:8]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix='.' + path.name, suffix='.tmp', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Saved data must be an object.')
    return value


def create_run(root: Path, metadata: dict) -> Path:
    directory = root.resolve() / new_id()
    directory.mkdir(parents=True)
    (directory / 'plans').mkdir()
    write_json(directory / 'run.json', {
        'schema_version': 1, 'run_id': directory.name, 'started_at': timestamp(),
        **metadata,
    })
    return directory


def plan_path(root: Path, run_id: object, plan_id: object) -> Path:
    for value in (run_id, plan_id):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9._-]+', value) or value in {'.', '..'}:
            raise ValueError('Invalid saved plan identifier.')
    path = (root / str(run_id) / 'plans' / (str(plan_id) + '.json')).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Saved plan is outside the runs folder.')
    return path


def validate_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120 or any(ord(c) < 32 for c in value):
        raise ValueError('Plan name must contain 1–120 characters without control characters.')
    return value.strip()


def list_plans(root: Path, page: int = 1, page_size: int = 25) -> dict:
    if page < 1 or not 1 <= page_size <= 100:
        raise ValueError('Invalid pagination parameters.')
    items = []
    for path in root.glob('*/plans/*.json'):
        try:
            if path.resolve() != plan_path(root, path.parent.parent.name, path.stem):
                continue
            plan = read_json(path)
            items.append({
                'id': path.stem, 'runId': path.parent.parent.name,
                'name': plan['name'], 'createdAt': plan['created_at'],
                'updatedAt': plan.get('updated_at', plan['created_at']),
                'decisionCount': len(plan.get('decisions', [])),
                'roots': plan['review_context']['roots'],
            })
        except (OSError, ValueError, KeyError, TypeError):
            continue
    items.sort(key=lambda item: (item['createdAt'], item['id']), reverse=True)
    start = (page - 1) * page_size
    return {'items': items[start:start + page_size], 'page': page,
            'pageSize': page_size, 'total': len(items)}
