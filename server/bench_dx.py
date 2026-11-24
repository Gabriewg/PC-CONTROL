"""Benchmark da captura via Desktop Duplication (dxcam) com a tela em movimento."""

from __future__ import annotations

import threading
import time
import tkinter as tk

import cv2
import numpy as np

import dxcam

WIDTH, QUALITY = 1280, 65
result = {"frames": 0, "encode_ms": [], "grab_none": 0, "errors": 0}
stop = threading.Event()


def capturar() -> None:
    try:
        cam = dxcam.create(output_idx=0, output_color="BGR")
        print("camera:", cam)
    except Exception as exc:  # noqa: BLE001
        print("falha ao criar camera:", exc)
        stop.set()
        return

    deadline = time.perf_counter() + 5
    while not stop.is_set() and time.perf_counter() < deadline:
        t0 = time.perf_counter()
        frame = cam.grab()
        if frame is None:
            result["grab_none"] += 1
            time.sleep(0.002)
            continue
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (WIDTH, int(h * WIDTH / w)), interpolation=cv2.INTER_AREA)
        ok, out = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), QUALITY])
        result["encode_ms"].append((time.perf_counter() - t0) * 1000)
        result["frames"] += 1


threading.Thread(target=capturar, daemon=True).start()

root = tk.Tk()
root.geometry("320x220+120+120")
root.title("anim")
canvas = tk.Canvas(root, width=320, height=220, bg="black")
canvas.pack()
rect = canvas.create_rectangle(0, 0, 60, 60, fill="#2E9BFF")
state = [0]


def animar() -> None:
    state[0] = (state[0] + 7) % 240
    canvas.coords(rect, state[0], state[0] % 140, state[0] + 60, (state[0] % 140) + 60)
    root.after(10, animar)


root.after(10, animar)
fim = time.perf_counter() + 4.0
while time.perf_counter() < fim:
    root.update()
    time.sleep(0.001)
root.destroy()
stop.set()
time.sleep(0.3)

n = result["frames"]
if n:
    avg = sum(result["encode_ms"]) / n
    print(f"quadros capturados: {n} em ~4s ({n / 4:.1f} fps)")
    print(f"grab+encode medio : {avg:.2f} ms  (grab vazio: {result['grab_none']})")
else:
    print("nenhum quadro capturado (grab vazio:", result["grab_none"], ")")
