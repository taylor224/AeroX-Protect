"""Encoder node agent pure logic: reconcile diff + ffmpeg argv allow-list validation.
No httpx/ffmpeg needed (lazy/subprocess-free here)."""
from worker.encoder.node_agent import NodeAgent, build_live_cmd

SPEC = {'camera_id': 1, 'epoch': 1,
        'pull_url': 'rtsp://go2rtc:8554/cam_1_sub_raw',
        'publish_url': 'rtsp://go2rtc:8554/cam_1_sub_enc',
        'v_codec': 'libx264', 'preset': 'veryfast', 'crf': 23, 'a_codec': 'aac'}


def test_reconcile_start_stop_update():
    s2 = {**SPEC, 'camera_id': 2}
    to_start, to_stop, to_update = NodeAgent.reconcile([SPEC, s2], {})
    assert [s['camera_id'] for s in to_start] == [1, 2] and to_stop == [] and to_update == []

    to_start, to_stop, to_update = NodeAgent.reconcile([SPEC], {1: SPEC, 2: s2})
    assert to_start == [] and to_stop == [2] and to_update == []

    bumped = {**SPEC, 'epoch': 2}
    to_start, to_stop, to_update = NodeAgent.reconcile([bumped], {1: SPEC})
    assert to_start == [] and to_stop == [] and to_update == [bumped]


def test_build_live_cmd_shape():
    cmd = build_live_cmd(SPEC)
    assert cmd[0] == 'ffmpeg' and SPEC['pull_url'] in cmd and cmd[-1] == SPEC['publish_url']
    assert 'libx264' in cmd and '-crf' in cmd and 'veryfast' in cmd
    assert '-f' in cmd and 'rtsp' in cmd


def test_build_live_cmd_rejects_bad_specs():
    assert build_live_cmd({**SPEC, 'pull_url': 'http://evil/x'}) is None
    assert build_live_cmd({**SPEC, 'publish_url': 'file:///etc/passwd'}) is None
    assert build_live_cmd({**SPEC, 'v_codec': '; rm -rf /'}) is None
    assert build_live_cmd({**SPEC, 'preset': '-vf evil'}) is None
    assert build_live_cmd({**SPEC, 'crf': 'x'}) is None


def test_build_live_cmd_clamps_crf():
    cmd = build_live_cmd({**SPEC, 'crf': 999})
    assert cmd[cmd.index('-crf') + 1] == '51'
    cmd = build_live_cmd({**SPEC, 'crf': -5})
    assert cmd[cmd.index('-crf') + 1] == '0'
