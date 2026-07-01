from types import SimpleNamespace

from server.service.go2rtc_sync import build_source, remove_camera, sync_camera


def _cam(streams, host='10.0.0.5', rtsp_port=554, creds=('admin', 'p@ss'), enabled=True):
    return SimpleNamespace(host=host, rtsp_port=rtsp_port, is_enabled=enabled,
                           get_credentials=lambda: creds, streams=streams)


def _stream(name='cam_x_sub', path='/Streaming/Channels/102', enabled=True):
    return SimpleNamespace(go2rtc_name=name, rtsp_path=path, enabled=enabled)


def test_build_source_injects_credentials_and_copy():
    src = build_source(_cam([]), _stream())
    assert src == 'rtsp://admin:p%40ss@10.0.0.5:554/Streaming/Channels/102#video=copy#audio=copy'


def test_build_source_without_credentials():
    src = build_source(_cam([], creds=(None, None)), _stream(path='/live'))
    assert src == 'rtsp://10.0.0.5:554/live#video=copy#audio=copy'


def test_build_source_live_transcode_h264():
    # live_transcode ON → the default-live stream is transcoded to H.264 (one shared go2rtc producer)
    cam = _cam([])
    cam.live_transcode = True
    live = _stream(path='/live')
    live.is_default_live = True
    assert build_source(cam, live) == 'ffmpeg:rtsp://admin:p%40ss@10.0.0.5:554/live#video=h264#audio=aac'
    # a non-default-live (e.g. main/archive) stream stays copy even with the flag on
    main = _stream(path='/main')
    main.is_default_live = False
    assert build_source(cam, main) == 'rtsp://admin:p%40ss@10.0.0.5:554/main#video=copy#audio=copy'
    # transcode also honors forced tcp transport
    cam.rtsp_transport = 'tcp'
    assert build_source(cam, live) == 'ffmpeg:rtsp://admin:p%40ss@10.0.0.5:554/live#input=rtsp/tcp#video=h264#audio=aac'


def test_build_source_auto_transcode_h265():
    # an H.265 default-live stream is auto-transcoded to H.264 even without the flag —
    # browsers can't decode HEVC over MSE/WebRTC.
    cam = _cam([])
    live = _stream(path='/live')
    live.is_default_live = True
    live.codec = 'h265'
    assert build_source(cam, live) == 'ffmpeg:rtsp://admin:p%40ss@10.0.0.5:554/live#video=h264#audio=aac'
    # H.264 default-live stays copy (no needless transcode)
    live.codec = 'h264'
    assert build_source(cam, live) == 'rtsp://admin:p%40ss@10.0.0.5:554/live#video=copy#audio=copy'


def test_build_source_rtsp_transport():
    # tcp/udp force the transport via go2rtc's ffmpeg source preset
    cam_udp = _cam([])
    cam_udp.rtsp_transport = 'udp'
    assert build_source(cam_udp, _stream(path='/live')) == \
        'ffmpeg:rtsp://admin:p%40ss@10.0.0.5:554/live#input=rtsp/udp#video=copy#audio=copy'
    cam_tcp = _cam([])
    cam_tcp.rtsp_transport = 'tcp'
    assert build_source(cam_tcp, _stream(path='/live')).startswith('ffmpeg:rtsp://')
    # auto / unknown → native go2rtc rtsp source (no ffmpeg wrapper)
    cam_auto = _cam([])
    cam_auto.rtsp_transport = 'auto'
    assert build_source(cam_auto, _stream(path='/live')) == 'rtsp://admin:p%40ss@10.0.0.5:554/live#video=copy#audio=copy'


def test_sync_camera_puts_each_enabled_stream():
    calls = []

    class FakeDriver:
        def put_stream(self, name, src):
            calls.append((name, src))

    cam = _cam([_stream('cam_x_main', '/main'), _stream('cam_x_sub', '/sub', enabled=False)])
    result = sync_camera(cam, driver=FakeDriver())
    assert calls == [('cam_x_main', 'rtsp://admin:p%40ss@10.0.0.5:554/main#video=copy#audio=copy')]
    assert result['cam_x_main']['ok'] is True


def test_remove_camera_deletes_each_stream():
    deleted = []

    class FakeDriver:
        def delete_stream(self, name):
            deleted.append(name)

    remove_camera(_cam([_stream('cam_x_main'), _stream('cam_x_sub')]), driver=FakeDriver())
    assert deleted == ['cam_x_main', 'cam_x_sub']
