"""Compara mss x BitBlt direto (GDI) para achar o custo real da captura."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

import cv2
import mss
import numpy as np

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

user32.GetDC.restype = ctypes.c_void_p
user32.GetDC.argtypes = [ctypes.c_void_p]
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.CreateDIBSection.restype = ctypes.c_void_p
gdi32.CreateDIBSection.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
    ctypes.c_void_p, wintypes.DWORD,
]
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.BitBlt.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL

SRCCOPY = 0x00CC0020


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class GDICapture:
    def __init__(self, x: int, y: int, w: int, h: int) -> None:
        self.x, self.y, self.w, self.h = x, y, w, h
        self.screen = user32.GetDC(None)
        self.memdc = gdi32.CreateCompatibleDC(self.screen)

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        self.ppv = ctypes.c_void_p()
        self.hbitmap = gdi32.CreateDIBSection(
            self.screen, ctypes.byref(bmi), 0, ctypes.byref(self.ppv), None, 0
        )
        gdi32.SelectObject(self.memdc, self.hbitmap)
        self.buf = (ctypes.c_ubyte * (w * h * 4)).from_address(self.ppv.value)
        self.view = np.frombuffer(self.buf, dtype=np.uint8).reshape(h, w, 4)

    def grab(self) -> np.ndarray:
        gdi32.BitBlt(self.memdc, 0, 0, self.w, self.h, self.screen, self.x, self.y, SRCCOPY)
        return self.view


factory = getattr(mss, "MSS", None) or mss.mss
sct = factory()
mon = sct.monitors[1]
x, y, w, h = mon["left"], mon["top"], mon["width"], mon["height"]

cap = GDICapture(x, y, w, h)
WIDTH, QUALITY, N = 1280, 65, 40

for _ in range(5):
    sct.grab(mon)
    cap.grab()

t0 = time.perf_counter()
for _ in range(N):
    sct.grab(mon)
mss_ms = (time.perf_counter() - t0) / N * 1000

t0 = time.perf_counter()
for _ in range(N):
    arr = cap.grab()
gdi_ms = (time.perf_counter() - t0) / N * 1000

print(f"mss grab    : {mss_ms:6.2f} ms")
print(f"BitBlt direto: {gdi_ms:6.2f} ms")

# pipeline completa com BitBlt reaproveitando o buffer
times = []
for _ in range(N):
    t = time.perf_counter()
    arr = cap.grab()
    small = cv2.resize(arr, (WIDTH, int(h * WIDTH / w)), interpolation=cv2.INTER_AREA)
    bgr = cv2.cvtColor(small, cv2.COLOR_BGRA2BGR)
    ok, out = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), QUALITY])
    times.append((time.perf_counter() - t) * 1000)

avg = sum(times) / len(times)
print(f"pipeline GDI: {avg:6.2f} ms -> {1000 / avg:5.1f} fps ({len(out) / 1024:.0f} KB)")
