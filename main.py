from tkinter import *
from tkinter import ttk
import time
import os

import cv2
import numpy as np
from PIL import ImageGrab, Image, ImageTk
import pydirectinput

import pygetwindow as gw
import win32gui
import win32con
import win32api


TEMPLATE_PATH = os.path.join("assets", "golden_start.png")
MATCH_THRESHOLD = 0.8
SCAN_INTERVAL_MS = 1000

PIZZA_LETTERS = ['c', 'm', 'p', 'd']
PIZZA_THRESHOLD = 0.6

PIZZA_REGION = (877, 272, 1043, 441)

DIALOGUE_REGION = (60, 705, 406, 917)
WHITE_FRACTION = 0.15

# color used as the transparent/click-through key for the overlay
OVERLAY_KEY = "magenta"


def load_with_mask(path):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"Couldn't load {path}")
    if img.shape[2] == 4:
        bgr = img[:, :, :3].copy()
        alpha = img[:, :, 3]
        mask = cv2.cvtColor(alpha, cv2.COLOR_GRAY2BGR)
        return bgr, mask
    return img, None


pizza_templates = {}
for letter in PIZZA_LETTERS:
    path = os.path.join("assets", f"{letter}_texture.png")
    pizza_templates[letter] = load_with_mask(path)

template = cv2.imread(TEMPLATE_PATH, cv2.IMREAD_COLOR)
tpl_h, tpl_w = template.shape[:2]

line_y = None
grid_cells = None
farm_enabled = False
region_overlay = None

root = Tk()
root.title("loadstring.net")
root.configure(bg="#1a1a1a")
root.resizable(False, False)
root.attributes("-topmost", True)

# ---- dark theme ----
BG = "#1a1a1a"
CARD = "#242424"
FG = "#e0e0e0"
MUTED = "#888888"
ACCENT = "#c04040"

style = ttk.Style()
style.theme_use("clam")
style.configure("TFrame", background=BG)
style.configure("Card.TFrame", background=CARD)
style.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
style.configure("Title.TLabel", background=BG, foreground=FG,
                font=("Segoe UI Semibold", 13))
style.configure("Muted.TLabel", background=BG, foreground=MUTED,
                font=("Segoe UI", 9))
style.configure("TButton", background=CARD, foreground=FG,
                font=("Segoe UI", 10), borderwidth=0, focuscolor=BG,
                padding=(10, 6))
style.map("TButton",
          background=[("active", "#303030"), ("pressed", ACCENT)],
          foreground=[("active", FG)])

frm = ttk.Frame(root, padding=16)
frm.grid(sticky="nsew")

ttk.Label(frm, text="Work at a Pizza Place Autofarm",
          style="Title.TLabel").grid(column=0, row=0, columnspan=2,
                                     sticky="w", pady=(0, 12))

# --- buttons (left column) ---
btns = ttk.Frame(frm)
btns.grid(column=0, row=1, sticky="nw", padx=(0, 16))

ttk.Button(btns, text="Toggle Autofarm",
           command=lambda: toggle_farm()).grid(column=0, row=0, sticky="ew", pady=2)
ttk.Button(btns, text="Set Line Position",
           command=lambda: select_line_location(line_status)).grid(column=0, row=1, sticky="ew", pady=2)
ttk.Button(btns, text="Set Grid Position",
           command=lambda: select_grid_location(grid_status)).grid(column=0, row=2, sticky="ew", pady=2)
overlay_btn = ttk.Button(btns, text="Show Regions", command=lambda: toggle_region_overlay())
overlay_btn.grid(column=0, row=3, sticky="ew", pady=2)
ttk.Button(btns, text="Quit",
           command=root.destroy).grid(column=0, row=4, sticky="ew", pady=2)

# --- status (right column) ---
stat = ttk.Frame(frm)
stat.grid(column=1, row=1, sticky="nw")

toggle_label = ttk.Label(stat, text=f"Toggled: {farm_enabled}")
toggle_label.grid(column=0, row=0, sticky="w", pady=2)

line_status = ttk.Label(stat, text="Line Y: Not set", style="Muted.TLabel")
line_status.grid(column=0, row=1, sticky="w", pady=2)

grid_status = ttk.Label(stat, text="Grid: Not set", style="Muted.TLabel")
grid_status.grid(column=0, row=2, sticky="w", pady=2)

detect_status = ttk.Label(stat, text="Detection: idle", style="Muted.TLabel")
detect_status.grid(column=0, row=3, sticky="w", pady=2)

# --- ad image (bottom-right, overlaid so it doesn't resize the window) ---
AD_PATH = os.path.join("assets", "ad.png")
try:
    _ad = Image.open(AD_PATH).convert("RGBA").resize((111, 69), Image.LANCZOS)
    ad_img = ImageTk.PhotoImage(_ad)
    ad_label = Label(frm, image=ad_img, bg=BG, borderwidth=0)
    ad_label.place(relx=1.0, rely=1.0, anchor="se")
except Exception as e:
    print("ad load failed:", e)


def focus_roblox():
    wins = gw.getWindowsWithTitle("Roblox")
    if not wins:
        detect_status.config(text="Roblox window not found. Is roblox open?")
        return False
    win = wins[0]
    hwnd = win._hWnd

    try:
        if win.isMinimized:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception as e:
        detect_status.config(text=f"Focus failed: {e}")
        return False


def find_dialogue():
    left, top, right, bottom = DIALOGUE_REGION
    shot = ImageGrab.grab(bbox=DIALOGUE_REGION)
    arr = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2BGR)

    mask = cv2.inRange(arr, np.array([200, 200, 200]), np.array([255, 255, 255]))
    white_frac = np.count_nonzero(mask) / mask.size
    if white_frac < WHITE_FRACTION:
        return None

    cx = (left + right) // 2
    cy = (top + bottom) // 2
    return cx, cy


def find_target_pizza():
    shot = ImageGrab.grab(bbox=PIZZA_REGION)
    region = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2BGR)
    rh, rw = region.shape[:2]

    best_letter, best_score = None, 0
    scores = {}
    for letter, (tpl, mask) in pizza_templates.items():
        th, tw = tpl.shape[:2]
        letter_best = 0
        for scale in np.linspace(0.4, 1.3, 10):
            w, h = int(tw * scale), int(th * scale)
            if w < 10 or h < 10 or w > rw or h > rh:
                continue
            rt = cv2.resize(tpl, (w, h))
            if mask is not None:
                rm = cv2.resize(mask, (w, h))
                result = cv2.matchTemplate(region, rt, cv2.TM_CCOEFF_NORMED, mask=rm)
            else:
                result = cv2.matchTemplate(region, rt, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            if max_val > letter_best:
                letter_best = max_val
        scores[letter] = round(letter_best, 3)
        if letter_best > best_score:
            best_score, best_letter = letter_best, letter

    print("pizza scores:", scores)

    if best_score >= PIZZA_THRESHOLD:
        return best_letter, best_score
    return None


def click_at(x, y):
    cur_x, cur_y = win32api.GetCursorPos()
    dx, dy = x - cur_x, y - cur_y
    win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, dx, dy, 0, 0)
    time.sleep(0.1)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.02)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def toggle_farm():
    global farm_enabled
    farm_enabled = not farm_enabled
    toggle_label.config(text=f"Toggled: {str(farm_enabled)}")


# ---------- region overlay (camera alignment helper) ----------

def draw_overlay_boxes(canvas):
    """Draw all configured zones onto the overlay canvas."""
    canvas.delete("all")

    # pizza region (cyan)
    l, t, r, b = PIZZA_REGION
    canvas.create_rectangle(l, t, r, b, outline="cyan", width=3)
    canvas.create_text(l + 4, t - 10, text="PIZZA", fill="cyan",
                       anchor="w", font=("Arial", 11, "bold"))

    # line (red)
    if line_y is not None:
        w = canvas.winfo_screenwidth()
        canvas.create_line(0, line_y, w, line_y, fill="red", width=2)
        canvas.create_text(10, line_y - 10, text="LINE", fill="red",
                           anchor="w", font=("Arial", 11, "bold"))

    # grid cells (lime dots + labels)
    if grid_cells is not None:
        for letter, (gx, gy) in grid_cells.items():
            canvas.create_oval(gx - 8, gy - 8, gx + 8, gy + 8,
                               outline="lime", width=3)
            canvas.create_text(gx, gy - 16, text=letter.upper(), fill="lime",
                               font=("Arial", 12, "bold"))


def toggle_region_overlay():
    global region_overlay

    if region_overlay is not None:
        region_overlay.destroy()
        region_overlay = None
        overlay_btn.config(text="Show Regions")
        return

    region_overlay = Toplevel(root)
    region_overlay.attributes("-fullscreen", True)
    region_overlay.attributes("-topmost", True)
    region_overlay.configure(bg=OVERLAY_KEY)
    region_overlay.attributes("-transparentcolor", OVERLAY_KEY)

    canvas = Canvas(region_overlay, bg=OVERLAY_KEY, highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    draw_overlay_boxes(canvas)
    overlay_btn.config(text="Hide Regions")

    def refresh():
        if region_overlay is not None:
            draw_overlay_boxes(canvas)
            region_overlay.after(500, refresh)
    refresh()


# ---------- pickers ----------

def select_line_location(status_label):
    global line_y

    root.withdraw()

    overlay = Toplevel(root)
    overlay.attributes("-fullscreen", True)
    overlay.attributes("-topmost", True)
    overlay.attributes("-alpha", 0.35)
    overlay.configure(bg="black", cursor="crosshair")

    canvas = Canvas(overlay, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    canvas.create_text(
        overlay.winfo_screenwidth() // 2,
        40,
        text="Move the line up or down, then click to lock it\nPress Esc to cancel",
        fill="white",
        font=("Arial", 18)
    )

    line = canvas.create_line(
        0, 0, overlay.winfo_screenwidth(), 0, fill="red", width=3
    )

    def follow_mouse(event):
        canvas.coords(line, 0, event.y, overlay.winfo_width(), event.y)

    def lock_location(event):
        global line_y
        line_y = event.y_root
        status_label.config(text=f"Line Y: {line_y}")
        overlay.destroy()
        root.deiconify()

    def cancel(event=None):
        overlay.destroy()
        root.deiconify()

    overlay.bind("<Motion>", follow_mouse)
    overlay.bind("<Button-1>", lock_location)
    overlay.bind("<Escape>", cancel)
    overlay.focus_force()


def select_grid_location(status_label):
    global grid_cells

    root.withdraw()

    overlay = Toplevel(root)
    overlay.attributes("-fullscreen", True)
    overlay.attributes("-topmost", True)
    overlay.attributes("-alpha", 0.30)
    overlay.configure(bg="black", cursor="crosshair")

    canvas = Canvas(overlay, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    canvas.create_text(
        overlay.winfo_screenwidth() // 2,
        40,
        text="Drag a box around the whole 2x2 pizza grid, then release\nPress Esc to cancel",
        fill="white",
        font=("Arial", 18)
    )

    start = {"x": 0, "y": 0}
    rect = {"id": None}

    def on_press(event):
        start["x"] = event.x_root
        start["y"] = event.y_root
        rect["id"] = canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="lime", width=2
        )

    def on_drag(event):
        x0 = start["x"] - overlay.winfo_rootx()
        y0 = start["y"] - overlay.winfo_rooty()
        canvas.coords(rect["id"], x0, y0, event.x, event.y)

    def on_release(event):
        global grid_cells
        left = min(start["x"], event.x_root)
        top = min(start["y"], event.y_root)
        right = max(start["x"], event.x_root)
        bottom = max(start["y"], event.y_root)

        qx = (right - left) / 4
        qy = (bottom - top) / 4
        lc, rc = int(left + qx), int(left + qx * 3)
        tr, br = int(top + qy), int(top + qy * 3)

        grid_cells = {
            'p': (lc, tr),
            'c': (rc, tr),
            'm': (lc, br),
            'd': (rc, br),
        }
        status_label.config(text="Grid: set")
        overlay.destroy()
        root.deiconify()

    def cancel(event=None):
        overlay.destroy()
        root.deiconify()

    canvas.bind("<Button-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    overlay.bind("<Escape>", cancel)
    overlay.focus_force()


def find_golden():
    shot = ImageGrab.grab()
    screen = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2BGR)
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val >= MATCH_THRESHOLD:
        x, y = max_loc
        return x + tpl_w // 2, y + tpl_h // 2, max_val
    return None


def scan_loop():
    if farm_enabled:
        dialogue = find_dialogue()
        if dialogue:
            cx, cy = dialogue
            click_at(cx, cy)
            detect_status.config(text="Dialogue clicked")
        else:
            match = find_golden()
            if match and line_y is not None:
                cx, cy, score = match
                if cy < line_y:
                    if focus_roblox():
                        pydirectinput.press('e')
                        detect_status.config(text=f"Above line ({score:.2f})")
                else:
                    detect_status.config(text=f"Below line ({score:.2f})")
            else:
                target = find_target_pizza()
                if target:
                    letter, score = target
                    if grid_cells is not None:
                        x, y = grid_cells[letter]
                        click_at(x, y)
                        detect_status.config(text=f"Order '{letter}' ({score:.2f}) -> grid")
                    else:
                        detect_status.config(text="Order found but grid not set")
                else:
                    detect_status.config(text="Idle")
    root.after(SCAN_INTERVAL_MS, scan_loop)


root.after(SCAN_INTERVAL_MS, scan_loop)
root.mainloop()