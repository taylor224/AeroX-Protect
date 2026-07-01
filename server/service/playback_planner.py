"""Timeline/playback planning from the segment index (PLAN P2 §7.1, §7.2)."""
from datetime import datetime

from server.model import to_epoch_ms
from server.model.segment import Segment

GAP_MERGE_FACTOR = 2   # merge adjacent segments whose gap < factor × segment duration


def build_timeline(camera_id: int, start: datetime, end: datetime) -> dict:
    """Continuous recording ranges + gaps for the scrub bar."""
    segments = Segment.get_range(camera_id, start, end)
    ranges: list[dict] = []
    current = None
    for seg in segments:
        seg_gap_limit = GAP_MERGE_FACTOR * max(1.0, (seg.duration_ms or 10000) / 1000.0)
        if current and (seg.start_ts - current['end']).total_seconds() <= seg_gap_limit:
            current['end'] = max(current['end'], seg.end_ts)
        else:
            if current:
                ranges.append(current)
            current = {'start': seg.start_ts, 'end': seg.end_ts}
    if current:
        ranges.append(current)

    gaps = []
    cursor = start
    for r in ranges:
        if r['start'] > cursor:
            gaps.append({'start': cursor, 'end': r['start']})
        cursor = max(cursor, r['end'])
    if cursor < end:
        gaps.append({'start': cursor, 'end': end})

    return {
        'ranges': [{'start': to_epoch_ms(r['start']), 'end': to_epoch_ms(r['end'])} for r in ranges],
        'gaps': [{'start': to_epoch_ms(g['start']), 'end': to_epoch_ms(g['end'])} for g in gaps],
        'events': [],    # P3
        'objects': [],   # P4
    }


def get_segments(camera_id: int, start: datetime, end: datetime) -> list[dict]:
    return [s.to_dict() for s in Segment.get_range(camera_id, start, end)]


def _iso_utc(dt: datetime) -> str:
    """Naive-UTC datetime → ISO-8601 with ms and a Z suffix (for #EXT-X-PROGRAM-DATE-TIME)."""
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def build_m3u8(camera_id: int, start: datetime, end: datetime, token: str,
               transcode: bool = False) -> str:
    """HLS VOD playlist for hls.js. Media segments are MPEG-TS served from
    /playback/segments/{id}/hls (raw for .ts, remuxed for legacy fMP4, or transcoded to
    H.264 when `transcode` is set — for H.265 recordings in browsers that can't decode HEVC).
    #EXT-X-PROGRAM-DATE-TIME stamps each segment's wall-clock start so the player can map the
    playhead to real time across gaps (#EXT-X-DISCONTINUITY)."""
    import math
    segments = Segment.get_range(camera_id, start, end)
    target = max((math.ceil((s.duration_ms or 10000) / 1000.0) for s in segments), default=10)
    lines = ['#EXTM3U', '#EXT-X-VERSION:3', '#EXT-X-PLAYLIST-TYPE:VOD',
             '#EXT-X-TARGETDURATION:%d' % target, '#EXT-X-MEDIA-SEQUENCE:0']
    q = '?access_token=%s' % token + ('&transcode=h264' if transcode else '')
    prev_end = None
    for seg in segments:
        if prev_end is not None and (seg.start_ts - prev_end).total_seconds() > 1:
            lines.append('#EXT-X-DISCONTINUITY')
        lines.append('#EXT-X-PROGRAM-DATE-TIME:%s' % _iso_utc(seg.start_ts))
        lines.append('#EXTINF:%.3f,' % ((seg.duration_ms or 10000) / 1000.0))
        lines.append('/api/v1/playback/segments/%s/hls%s' % (seg.id, q))
        prev_end = seg.end_ts
    lines.append('#EXT-X-ENDLIST')
    return '\n'.join(lines) + '\n'
