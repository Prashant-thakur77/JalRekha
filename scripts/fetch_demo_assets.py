from __future__ import annotations

import urllib.request
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEDIA_DIR = PROJECT_ROOT / 'fixtures' / 'media'
FRAME_DIR = PROJECT_ROOT / 'fixtures' / 'frames'
VIDEO_PATH = MEDIA_DIR / 'usgs_silverado_fire_2015_fixed_cam.mp4'
SOURCE_PAGE_URL = 'https://www.usgs.gov/media/videos/post-wildfire-flood-and-debris-flow-2014-silverado-fire'
DIRECT_VIDEO_URL = (
    'https://usgs-ocapsv2-public-input-media.s3.us-west-2.amazonaws.com/'
    'assets/palladium/production/s3fs-public/FinalFire.mp4'
)
FRAME_SECONDS = (15, 30, 60, 90)


def download_video() -> None:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    if VIDEO_PATH.exists() and VIDEO_PATH.stat().st_size > 0:
        print(f'Clip already present: {VIDEO_PATH}')
        return

    print(f'Downloading demo clip from {SOURCE_PAGE_URL}')
    with urllib.request.urlopen(DIRECT_VIDEO_URL) as response, VIDEO_PATH.open('wb') as target:
        target.write(response.read())
    print(f'Saved clip to {VIDEO_PATH}')


def extract_reference_frames() -> None:
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg is None:
        raise RuntimeError('ffmpeg is required to extract reference frames')

    for second in FRAME_SECONDS:
        output_path = FRAME_DIR / f'silverado_{second:03d}s.jpg'
        command = [
            ffmpeg,
            '-hide_banner',
            '-loglevel',
            'error',
            '-y',
            '-ss',
            str(second),
            '-i',
            str(VIDEO_PATH),
            '-frames:v',
            '1',
            '-q:v',
            '3',
            str(output_path),
        ]
        subprocess.run(command, check=True)
        print(f'Wrote {output_path}')


if __name__ == '__main__':
    download_video()
    extract_reference_frames()
