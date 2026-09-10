"""Capture real Win32 window, shell and taskbar icon evidence without app changes."""
from __future__ import annotations

import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from PIL import Image, ImageGrab

u = c.WinDLL("user32", use_last_error=True)
g = c.WinDLL("gdi32", use_last_error=True)
s = c.WinDLL("shell32", use_last_error=True)
u.SetProcessDPIAware()
u.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
u.SendMessageW.restype = c.c_ssize_t
u.GetClassLongPtrW.argtypes = [w.HWND, c.c_int]
u.GetClassLongPtrW.restype = c.c_size_t
u.GetWindow.argtypes = [w.HWND, w.UINT]
u.GetWindow.restype = w.HWND
u.GetWindowLongW.argtypes = [w.HWND, c.c_int]
u.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
u.SetForegroundWindow.argtypes = [w.HWND]
u.FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]
u.FindWindowW.restype = w.HWND
u.GetDC.argtypes = [w.HWND]
u.GetDC.restype = w.HDC
u.ReleaseDC.argtypes = [w.HWND, w.HDC]
u.DrawIconEx.argtypes = [w.HDC, c.c_int, c.c_int, w.HICON, c.c_int, c.c_int,
                        w.UINT, w.HBRUSH, w.UINT]
u.PrintWindow.argtypes = [w.HWND, w.HDC, w.UINT]
u.DestroyIcon.argtypes = [w.HICON]
g.CreateCompatibleDC.argtypes = [w.HDC]
g.CreateCompatibleDC.restype = w.HDC
g.CreateDIBSection.argtypes = [w.HDC, c.c_void_p, w.UINT, c.c_void_p, w.HANDLE, w.DWORD]
g.CreateDIBSection.restype = w.HBITMAP
g.SelectObject.argtypes = [w.HDC, w.HANDLE]
g.SelectObject.restype = w.HANDLE
g.DeleteObject.argtypes = [w.HANDLE]
g.DeleteDC.argtypes = [w.HDC]


def icon_image(handle, size=32):
    # BITMAPINFOHEADER followed by an unused colour entry, top-down BGRA.
    import struct
    info = c.create_string_buffer(struct.pack("<IiiHHIIiiII", 40, size, -size, 1,
                                           32, 0, size * size * 4, 0, 0, 0, 0) + b"\0" * 4)
    screen = u.GetDC(None)
    dc = g.CreateCompatibleDC(screen)
    bits = c.c_void_p()
    bitmap = g.CreateDIBSection(screen, info, 0, c.byref(bits), None, 0)
    old = g.SelectObject(dc, bitmap)
    try:
        c.memset(bits, 255, size * size * 4)
        if not u.DrawIconEx(dc, 0, 0, handle, size, size, 0, None, 3):
            raise c.WinError(c.get_last_error())
        return Image.frombytes("RGBA", (size, size), c.string_at(bits, size * size * 4),
                               "raw", "BGRA").convert("RGB")
    finally:
        g.SelectObject(dc, old)
        g.DeleteObject(bitmap)
        g.DeleteDC(dc)
        u.ReleaseDC(None, screen)


def shell_icon(path, small):
    class SHFILEINFO(c.Structure):
        _fields_ = [("hIcon", w.HICON), ("iIcon", c.c_int), ("attributes", w.DWORD),
                    ("displayName", w.WCHAR * 260), ("typeName", w.WCHAR * 80)]
    s.SHGetFileInfoW.argtypes = [w.LPCWSTR, w.DWORD, c.POINTER(SHFILEINFO), w.UINT, w.UINT]
    s.SHGetFileInfoW.restype = c.c_size_t
    info = SHFILEINFO()
    if not s.SHGetFileInfoW(str(path), 0, c.byref(info), c.sizeof(info), 0x100 | int(small)):
        raise c.WinError(c.get_last_error())
    try:
        return icon_image(info.hIcon, 16 if small else 32)
    finally:
        u.DestroyIcon(info.hIcon)


def native_window_image(hwnd):
    import struct
    rect = w.RECT()
    u.GetWindowRect(hwnd, c.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    info = c.create_string_buffer(struct.pack("<IiiHHIIiiII", 40, width, -height, 1,
                                           32, 0, width * height * 4, 0, 0, 0, 0) + b"\0" * 4)
    screen = u.GetDC(None)
    dc = g.CreateCompatibleDC(screen)
    bits = c.c_void_p()
    bitmap = g.CreateDIBSection(screen, info, 0, c.byref(bits), None, 0)
    old = g.SelectObject(dc, bitmap)
    try:
        if not u.PrintWindow(hwnd, dc, 2):
            raise c.WinError(c.get_last_error())
        return Image.frombytes("RGBA", (width, height),
                               c.string_at(bits, width * height * 4), "raw", "BGRA").convert("RGB")
    finally:
        g.SelectObject(dc, old)
        g.DeleteObject(bitmap)
        g.DeleteDC(dc)
        u.ReleaseDC(None, screen)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = Path(__file__).resolve().parent / args.label
    out.mkdir(exist_ok=False)
    env = os.environ.copy()
    env.pop("QT_QPA_PLATFORM", None)
    if args.exe:
        env.pop("PYTHONPATH", None)
        env.pop("QT_PLUGIN_PATH", None)
        env["PATH"] = str(Path(env["SYSTEMROOT"]) / "System32") + ";" + env["SYSTEMROOT"]
    else:
        env["PYTHONPATH"] = str(root / "src")
    command = [str(args.exe)] if args.exe else [os.sys.executable, "-m", "dps_studio.gui"]
    report = {"command": command, "cwd": "D:/", "label": args.label}
    callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    u.EnumWindows.argtypes = [callback_type, w.LPARAM]
    windows = []

    @callback_type
    def visit(hwnd, _):
        pid = w.DWORD()
        u.GetWindowThreadProcessId(hwnd, c.byref(pid))
        if pid.value == process.pid and u.IsWindowVisible(hwnd):
            title = c.create_unicode_buffer(512)
            u.GetWindowTextW(hwnd, title, 512)
            if "PDV Studio" in title.value:
                windows.append((hwnd, title.value))
        return True

    with (out / "stderr.txt").open("w", encoding="utf-8") as err:
        process = subprocess.Popen(command, cwd="D:/", env=env, stdout=err, stderr=err,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        hwnd = None
        try:
            deadline = time.monotonic() + 50
            while time.monotonic() < deadline and process.poll() is None:
                u.EnumWindows(visit, 0)
                if windows:
                    hwnd, title = windows[0]
                    break
                time.sleep(0.25)
            if not hwnd:
                raise RuntimeError(f"No PDV window; exit={process.poll()}")
            u.SetForegroundWindow(hwnd)
            time.sleep(2)
            report.update(pid=process.pid, title=title, visible=bool(u.IsWindowVisible(hwnd)),
                          responds_to_wm_null=u.SendMessageW(hwnd, 0, 0, 0) == 0,
                          owner=u.GetWindow(hwnd, 4),
                          tool_window=bool(u.GetWindowLongW(hwnd, -20) & 0x80))
            for kind, index, fallback in [("small", 0, -34), ("large", 1, -14)]:
                handle = u.SendMessageW(hwnd, 0x7F, index, 0) or u.GetClassLongPtrW(hwnd, fallback)
                report[f"window_{kind}_icon_present"] = bool(handle)
                if not handle:
                    raise RuntimeError(f"Missing {kind} icon")
                icon_image(handle, 16 if kind == "small" else 32).save(out / f"window_{kind}.png")
            shot = ImageGrab.grab(window=hwnd)
            shot.save(out / "window.png")
            native = native_window_image(hwnd)
            native.save(out / "native_window.png")
            native.crop((0, 0, 500, 90)).save(out / "native_titlebar.png")
            rect = w.RECT()
            u.GetWindowRect(hwnd, c.byref(rect))
            report["window_rect"] = [rect.left, rect.top, rect.right, rect.bottom]
            # Direct screen capture includes native chrome, unlike PrintWindow.
            ImageGrab.grab(bbox=(max(0, rect.left), max(0, rect.top),
                                 max(0, rect.left) + 500, max(0, rect.top) + 65)
                           ).save(out / "titlebar.png")
            tray = u.FindWindowW("Shell_TrayWnd", None)
            if tray:
                u.GetWindowRect(tray, c.byref(rect))
                ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom)
                               ).save(out / "taskbar.png")
            if args.exe:
                for small in (False, True):
                    shell_icon(args.exe, small).save(out / f"shell_{'small' if small else 'large'}.png")
                report["exe_sha256"] = hashlib.sha256(args.exe.read_bytes()).hexdigest()
            report["startup_pass"] = True
        finally:
            if hwnd:
                u.PostMessageW(hwnd, 0x10, 0, 0)
            try:
                report["exit_code"] = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                report["forced_close"] = True
                report["exit_code"] = process.wait(timeout=10)
            (out / "smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
