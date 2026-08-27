"""Windows process containment: Job Object + console ctrl events (ctypes, stdlib only).

Every child (and its ffmpeg grandchildren) is assigned to one Job Object created
with KILL_ON_JOB_CLOSE — if the launcher dies for any reason, the OS reaps the
whole tree; an orphaned ffmpeg.exe holding a recording file open is impossible.

Graceful stop: the launcher AllocConsole()s once (invisible under a service);
children are spawned WITHOUT CREATE_NO_WINDOW so they inherit that console, and
WITH CREATE_NEW_PROCESS_GROUP so GenerateConsoleCtrlEvent(CTRL_BREAK, pid) hits
only that child's group. Python children see SIGBREAK; celery/waitress/our
recorder all map it to a warm shutdown.

On non-Windows platforms (dev runs of the launcher) everything degrades to
POSIX signals.
"""
import os
import signal
import subprocess

IS_WINDOWS = os.name == 'nt'

CREATE_NEW_PROCESS_GROUP = 0x00000200
CTRL_BREAK_EVENT = 1

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    _JobObjectExtendedLimitInformation = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ('PerProcessUserTimeLimit', wintypes.LARGE_INTEGER),
            ('PerJobUserTimeLimit', wintypes.LARGE_INTEGER),
            ('LimitFlags', wintypes.DWORD),
            ('MinimumWorkingSetSize', ctypes.c_size_t),
            ('MaximumWorkingSetSize', ctypes.c_size_t),
            ('ActiveProcessLimit', wintypes.DWORD),
            ('Affinity', ctypes.POINTER(wintypes.ULONG)),
            ('PriorityClass', wintypes.DWORD),
            ('SchedulingClass', wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ('ReadOperationCount', ctypes.c_ulonglong),
            ('WriteOperationCount', ctypes.c_ulonglong),
            ('OtherOperationCount', ctypes.c_ulonglong),
            ('ReadTransferCount', ctypes.c_ulonglong),
            ('WriteTransferCount', ctypes.c_ulonglong),
            ('OtherTransferCount', ctypes.c_ulonglong),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ('BasicLimitInformation', _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ('IoInfo', _IO_COUNTERS),
            ('ProcessMemoryLimit', ctypes.c_size_t),
            ('JobMemoryLimit', ctypes.c_size_t),
            ('PeakProcessMemoryUsed', ctypes.c_size_t),
            ('PeakJobMemoryUsed', ctypes.c_size_t),
        ]


def alloc_console():
    """Give the (session-0, windowless) service process a console so children can
    inherit it — the transport for CTRL_BREAK events. No-op if one exists."""
    if IS_WINDOWS:
        _kernel32.AllocConsole()          # fails harmlessly if already attached
        # Never let a stray ctrl event kill the launcher itself.
        _kernel32.SetConsoleCtrlHandler(None, True)


class JobObject:
    def __init__(self):
        self._handle = None
        if not IS_WINDOWS:
            return
        handle = _kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _kernel32.SetInformationJobObject(
            handle, _JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        self._handle = handle

    def assign(self, popen: subprocess.Popen):
        if self._handle is None:
            return
        # Popen._handle is the process handle on Windows (stable CPython detail).
        _kernel32.AssignProcessToJobObject(self._handle, int(popen._handle))


def popen_flags() -> int:
    """creationflags for launcher children: own ctrl group, inherited console."""
    return CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0


def send_ctrl_break(popen: subprocess.Popen) -> bool:
    """Graceful-stop signal: CTRL_BREAK to the child's process group (Windows),
    SIGTERM elsewhere. Returns False if delivery failed."""
    try:
        if IS_WINDOWS:
            return bool(_kernel32.GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, popen.pid))
        popen.send_signal(signal.SIGTERM)
        return True
    except OSError:
        return False
