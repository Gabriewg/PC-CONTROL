# SPDX-License-Identifier: AGPL-3.0-or-later
"""Micro-benchmark do pipeline de captura/encode (para calibrar fps e qualidade)."""

from __future__ import annotations

import time

import cv2
import mss
import numpy as np

factory = getattr(mss, "MSS", None) or mss.mss
sct = factory()
mon = sct.monitors[1]
print("monitor:", mon)

WIDTH = 1280
QUALITY = 65
N = 40

# aquece
for _ in range(3):
    sct.grab(mon)

t_grab = t_resize = t_color = t_encode = 0.0
size = 0
for _ in range(N):
    a = time.perf_counter()
    shot = sct.grab(mon)
    b = time.perf_counter()
    arr = np.asarray(shot)
    frame = cv2.resize(arr, (WIDTH, int(arr.shape[0] * WIDTH / arr.shape[1])), interpolation=cv2.INTER_AREA)
    c = time.perf_counter()
    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    d = time.perf_counter()
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), QUALITY])
    e = time.perf_counter()
    size = len(buf)
    t_grab += b - a
    t_resize += c - b
    t_color += d - c
    t_encode += e - d

print(f"grab    {t_grab / N * 1000:6.1f} ms")
print(f"resize  {t_resize / N * 1000:6.1f} ms")
print(f"cor     {t_color / N * 1000:6.1f} ms")
print(f"encode  {t_encode / N * 1000:6.1f} ms")
total = (t_grab + t_resize + t_color + t_encode) / N * 1000
print(f"total   {total:6.1f} ms  -> {1000 / total:5.1f} fps  ({size / 1024:.0f} KB)")

# variantes
for w, q in ((1024, 60), (1280, 55), (1600, 70)):
    frames = []
    for _ in range(15):
        t0 = time.perf_counter()
        shot = sct.grab(mon)
        arr = np.asarray(shot)
        f = cv2.resize(arr, (w, int(arr.shape[0] * w / arr.shape[1])), interpolation=cv2.INTER_AREA)
        f = cv2.cvtColor(f, cv2.COLOR_BGRA2BGR)
        ok, buf = cv2.imencode(".jpg", f, [int(cv2.IMWRITE_JPEG_QUALITY), q])
        frames.append((time.perf_counter() - t0) * 1000)
    avg = sum(frames) / len(frames)
    print(f"{w}px q{q}: {avg:5.1f} ms -> {1000 / avg:4.1f} fps ({len(buf) / 1024:.0f} KB)")
