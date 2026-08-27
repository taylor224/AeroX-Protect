"""Windows-portability path handling in ffmpeg command building."""
from server.service import ffmpeg


def test_concat_entry_posix_path():
    assert ffmpeg.concat_entry('/mnt/axp/disk1/1/seg-a.ts') == "file '/mnt/axp/disk1/1/seg-a.ts'\n"


def test_concat_entry_windows_path_normalized():
    # backslashes are concat-demuxer escapes — must become forward slashes
    line = ffmpeg.concat_entry('C:\\axp\\disk1\\1\\seg-20260101-000000.ts')
    assert line == "file 'C:/axp/disk1/1/seg-20260101-000000.ts'\n"
    assert '\\' not in line


def test_concat_entry_mixed_separators_and_quote():
    line = ffmpeg.concat_entry("C:\\axp\\disk1/1/seg-o'clock.ts")
    assert line.startswith("file 'C:/axp/disk1/1/seg-o'")
    assert "'\\''" in line   # single-quote escaped for the concat parser


def test_escape_filter_path_windows_drive():
    # ':' is the filtergraph option separator; drive letters must be escaped
    assert ffmpeg.escape_filter_path('C:\\Windows\\Fonts\\arial.ttf') == r'C\:/Windows/Fonts/arial.ttf'


def test_escape_filter_path_posix_unchanged():
    assert ffmpeg.escape_filter_path('/usr/share/fonts/DejaVuSans.ttf') == '/usr/share/fonts/DejaVuSans.ttf'


def test_watermark_cmd_uses_escaped_font(monkeypatch):
    monkeypatch.setattr(ffmpeg, 'WATERMARK_FONT', 'C:\\Windows\\Fonts\\arial.ttf')
    cmd = ffmpeg.build_watermark_transcode_cmd('list.txt', 'out.mp4', 0.0, 10.0, 720, 'hello')
    vf = cmd[cmd.index('-vf') + 1]
    assert r'fontfile=C\:/Windows/Fonts/arial.ttf' in vf
