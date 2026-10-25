from __future__ import annotations

from sqlmodel import Session, select

from jalrekha.db.database import edge_engine, init_db
from jalrekha.models.domain import Site, SiteCalibration


def _upsert_site(session: Session, payload: dict[str, object]) -> None:
    site_id = str(payload['id'])
    site = session.get(Site, site_id)
    if site is None:
        session.add(Site(**payload))
        return

    for key, value in payload.items():
        setattr(site, key, value)


def _ensure_calibration(session: Session, payload: dict[str, object]) -> None:
    existing = session.exec(
        select(SiteCalibration)
        .where(SiteCalibration.site_id == str(payload['site_id']))
        .order_by(SiteCalibration.created_at.desc())
    ).first()
    if existing is not None:
        return
    session.add(SiteCalibration(**payload))


def seed() -> None:
    init_db()

    sites = [
        {
            'id': 'puente-arroyo-01',
            'name': 'Arroyo Bridge 01',
            'region': 'South Littoral',
            'lat': -32.9468,
            'lng': -60.6393,
            'description': 'Main bridge on provincial route',
            'is_active': True,
        },
        {
            'id': 'calle-baja-02',
            'name': 'Low Street 02',
            'region': 'North Littoral',
            'lat': -32.9568,
            'lng': -60.6493,
            'description': 'Frequently flooded low-water crossing',
            'is_active': True,
        },
        {
            'id': 'silverado-fixed-cam-usgs',
            'name': 'Silverado Fixed Cam (USGS)',
            'region': 'Orange County, California',
            'lat': 33.7471,
            'lng': -117.6416,
            'description': 'Demo site with official USGS fixed-camera clip for testing real flood and debris-flow analysis.',
            'sample_video_path': 'fixtures/media/usgs_silverado_fire_2015_fixed_cam.mp4',
            'sample_video_source_url': 'https://www.usgs.gov/media/videos/post-wildfire-flood-and-debris-flow-2014-silverado-fire',
            'sample_frame_path': 'fixtures/frames/silverado_060s.jpg',
            'is_active': True,
        },
    ]

    calibrations = [
        {
            'site_id': 'puente-arroyo-01',
            'roi_polygon': '[[0, 40], [640, 40], [640, 430], [0, 430]]',
            'critical_line': '[[0, 170], [640, 170]]',
            'reference_line': '[[0, 260], [640, 260]]',
            'notes': 'Default calibration expressed in frame pixels for a 640x480 reference clip.',
        },
        {
            'site_id': 'silverado-fixed-cam-usgs',
            'roi_polygon': '[[0, 70], [980, 70], [980, 265], [0, 265]]',
            'critical_line': '[[0, 118], [980, 118]]',
            'reference_line': '[[0, 190], [980, 190]]',
            'notes': 'USGS fixed camera reference frame 980x552. Search band focused on the upper channel to avoid the foreground vegetation and watermark.',
        },
    ]

    with Session(edge_engine) as session:
        for site_payload in sites:
            _upsert_site(session, site_payload)
        for calibration_payload in calibrations:
            _ensure_calibration(session, calibration_payload)
        session.commit()
        print(f'Seed complete. Sites available: {len(sites)}')


if __name__ == '__main__':
    seed()
