from datetime import timedelta

from server.model import db, utcnow
from server.model.camera import Camera
from server.model.disk import Disk
from server.model.segment import Segment
from server.service import ffmpeg, playback_planner


def _setup():
    c = Camera()
    c.name = 'c'
    c.host = 'h'
    c.vendor = 'onvif'
    c.driver = 'onvif'
    c.is_enabled = True
    db.session.add(c)
    d = Disk()
    d.name = 'd'
    d.mount_path = '/tmp/x'
    d.role = 'record'
    db.session.add(d)
    db.session.commit()
    return c, d


def _seg(c, d, start, dur=10):
    Segment.create(camera_id=c.id, disk_id=d.id, rel_path='%s/seg.mp4' % c.id,
                   start_ts=start, end_ts=start + timedelta(seconds=dur), duration_ms=dur * 1000, size_bytes=1000)


# ── playback planner ─────────────────────────────────────────────────────────
def test_timeline_merges_and_gaps(app_db):
    c, d = _setup()
    base = utcnow().replace(microsecond=0) - timedelta(hours=1)
    for i in range(3):
        _seg(c, d, base + timedelta(seconds=i * 10))   # contiguous → 1 range
    tl = playback_planner.build_timeline(c.id, base - timedelta(minutes=1), base + timedelta(minutes=5))
    assert len(tl['ranges']) == 1
    assert tl['events'] == [] and tl['objects'] == []

    _seg(c, d, base + timedelta(seconds=120))           # gap → 2 ranges
    tl = playback_planner.build_timeline(c.id, base - timedelta(minutes=1), base + timedelta(minutes=5))
    assert len(tl['ranges']) == 2
    assert len(tl['gaps']) >= 1


def test_segments_listing_excludes_paths(app_db):
    c, d = _setup()
    base = utcnow() - timedelta(minutes=10)
    _seg(c, d, base)
    segs = playback_planner.get_segments(c.id, base - timedelta(minutes=1), base + timedelta(minutes=1))
    assert len(segs) == 1
    assert 'rel_path' not in segs[0] and 'mount_path' not in str(segs)


# ── ffmpeg builders ──────────────────────────────────────────────────────────
def test_segment_cmd_fmp4_copy():
    cmd = ffmpeg.build_segment_cmd('rtsp://x/y', '/out/seg-%Y%m%d.mp4', 10, 'fmp4')
    assert 'segment' in cmd
    # video passthrough, audio transcoded to AAC (PCM/G.711 can't go in MP4)
    assert cmd[cmd.index('-c:v') + 1] == 'copy'
    assert cmd[cmd.index('-c:a') + 1] == 'aac'
    assert 'movflags=+frag_keyframe+empty_moov+default_base_moof' in cmd
    assert cmd[-1] == '/out/seg-%Y%m%d.mp4'


def test_segment_cmd_mpegts():
    assert 'mpegts' in ffmpeg.build_segment_cmd('rtsp://x', '/o.ts', 10, 'mpegts')


def test_concat_and_transcode():
    copy = ffmpeg.build_concat_copy_cmd('/l.txt', '/o.mp4', 1.5, 12.0)
    assert 'concat' in copy and 'copy' in copy and '1.500' in copy and '12.000' in copy
    trans = ffmpeg.build_transcode_cmd('/l.txt', '/o.mp4', 0, 10, 720)
    assert 'libx264' in trans and 'scale=-2:720' in trans


def test_preset_and_ext():
    assert ffmpeg.preset_height('h264_720p') == 720
    assert ffmpeg.preset_height(None) == 1080
    assert ffmpeg.segment_ext('mpegts') == 'ts' and ffmpeg.segment_ext('fmp4') == 'mp4'


def test_parse_probe():
    data = {'streams': [{'codec_type': 'video', 'codec_name': 'hevc', 'width': 2560, 'height': 1440},
                        {'codec_type': 'audio', 'codec_name': 'aac'}],
            'format': {'duration': '10.5'}}
    m = ffmpeg.parse_probe(data)
    assert m['video_codec'] == 'h265' and m['width'] == 2560 and m['has_audio'] and m['duration_ms'] == 10500
