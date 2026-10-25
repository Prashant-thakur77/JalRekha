from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from PIL import Image

from jalrekha.core.settings import get_settings


def get_upload_dir() -> Path:
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings.upload_dir


def get_fixture_dir() -> Path:
    settings = get_settings()
    return settings.project_root / 'fixtures'


def resolve_local_asset_path(path: str | None) -> Path | None:
    if not path:
        return None

    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return (get_settings().project_root / candidate).resolve()


def public_asset_url_for_path(path: str | None) -> str | None:
    resolved = resolve_local_asset_path(path)
    if resolved is None:
        return None

    upload_dir = get_upload_dir().resolve()
    fixture_dir = get_fixture_dir().resolve()

    try:
        relative_upload = resolved.relative_to(upload_dir)
        return f'/uploads/{relative_upload.as_posix()}'
    except ValueError:
        pass

    try:
        relative_fixture = resolved.relative_to(fixture_dir)
        return f'/fixtures/{relative_fixture.as_posix()}'
    except ValueError:
        return None


def persist_upload(file: UploadFile | None, prefix: str) -> str | None:
    if not file or not file.filename:
        return None

    safe_name = Path(file.filename).name
    extension = Path(safe_name).suffix or '.bin'
    stored_name = f'{prefix}-{uuid4().hex}{extension}'
    target_path = get_upload_dir() / stored_name
    file.file.seek(0)
    with target_path.open('wb') as buffer:
        buffer.write(file.file.read())
    return str(target_path)


def persist_frame_image(frame, prefix: str) -> str:
    target_path = get_upload_dir() / f'{prefix}-{uuid4().hex}.jpg'
    if isinstance(frame, Image.Image):
        frame.convert('RGB').save(target_path, format='JPEG', quality=85, optimize=True)
    else:
        raise TypeError('persist_frame_image now expects a PIL.Image; JalRekha Node no longer depends on OpenCV')
    return str(target_path)


def persist_json_artifact(payload: object, prefix: str) -> str:
    target_path = get_upload_dir() / f'{prefix}-{uuid4().hex}.json'
    with target_path.open('w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)
    return str(target_path)
