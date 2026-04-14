import json
import os
import queue
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

import pyautogui

# Settings are stored next to this script so they load automatically on launch.
SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

# --- UI palette (dark, Telegram-inspired) ---
BG = "#1f2023"      # window background
CARD = "#26282c"    # section cards
FIELD = "#2f3237"   # input fields / troughs
FG = "#e6e6e6"      # primary text
MUTED = "#9aa0a6"   # secondary text
BORDER = "#3a3d42"  # card & field borders
ACCENT = "#8ab4f8"  # section titles
GREEN = "#2e9e4f"   # Start button
RED = "#d93a3a"     # Stop button
LOG_BG = "#141518"
LOG_FG = "#c7cbd1"

# --- FAILSAFE ---
# Moving your mouse to any corner of the screen will instantly stop the script!
pyautogui.FAILSAFE = True


def get_date_cell(target_date, origin_x, origin_y, cell_w, cell_h):
    """Return the center of a date cell in a Sunday-first calendar grid.

    ``origin_x``/``origin_y`` are the center of the first visible cell (the
    top-left cell), not its corner. This is important because clicking a cell's
    center is more reliable than clicking near its edges or adjacent cells.
    The calendar must currently show ``target_date``'s month.
    """
    # Python weekday(): Monday=0; convert to Sunday=0.
    first_day_col = (target_date.replace(day=1).weekday() + 1) % 7
    cell_index = first_day_col + target_date.day - 1
    row, col = divmod(cell_index, 7)

    return (
        round(origin_x + col * cell_w),
        round(origin_y + row * cell_h),
    )


def months_between(start, end):
    """Return the signed number of calendar-month transitions from start to end."""
    return (end.year - start.year) * 12 + end.month - start.month

class _SchedulingStop(Exception):
    """Raised to abort a run the instant the user asks to stop."""
    pass


def schedule_messages(base_time, total_messages, interval_minutes, auto_click,
                      cal_origin_x, cal_origin_y, cal_cell_w, cal_cell_h,
                      typing_interval, stop_event, log, show_click, show_scheduled):
    """Runs the scheduling loop. `log` is a callable(msg) for progress output."""
    log("Starting... Press F9 (or slam mouse to a corner) to stop.")

    # Used so that sleeping is interruptible: 'nap' checks the stop flag every
    # ~20ms and aborts immediately instead of waiting out a long time.sleep().
    def nap(seconds):
        end = time.time() + seconds
        while time.time() < end:
            if stop_event.is_set():
                raise _SchedulingStop
            time.sleep(0.02)

    nap(1.0)

    # Telegram's calendar opens on the current month, so this is the anchor for
    # month navigation and is recomputed against the real "today" each run.    today = datetime.now()
    # The date of the first scheduled message; each next message is a day later.
    current_date = base_time.replace(hour=0, minute=0, second=0, microsecond=0)


    for day in range(1, total_messages + 1):
        if stop_event.is_set():
            raise _SchedulingStop

        # 1. Paste the command
        pyautogui.hotkey('ctrl', 'v')
        nap(0.2)

        # 2. Open the schedule dialog
        pyautogui.press('enter')
        nap(0.3)

        # Calculate the new time (shifting the clock forward by interval per loop)
        # `day` is 1-based, but the first message must use the selected
        # start time. Each later message is exactly `interval_minutes` later.
        run_time = base_time + timedelta(minutes=interval_minutes * (day - 1))
        time_string = run_time.strftime('%H%M')
        log(f"[{day}/{total_messages}] {current_date:%Y-%m-%d} {time_string}")

        # 3. Type the calculated time into the time input box
        pyautogui.press('backspace', presses=4, interval=typing_interval)  # Clear old time just in case
        # Type slowly enough for Telegram's time field to process every
        # keystroke; otherwise digits can be dropped or reordered.
        pyautogui.write(time_string, interval=typing_interval)
        nap(0.25)

        # 4. Focus the date picker / calendar.
        pyautogui.press('tab')
        nap(0.2)

        if auto_click:
            # 4a. Advance to the correct month. Telegram's month control is
            # focused after the Tab above; Down changes the month one step at a
            # time (the chevron itself is not a date-cell click target).
            months_to_advance = months_between(datetime.now(), current_date)
            if months_to_advance > 0:
                pyautogui.press('down', presses=months_to_advance, interval=0.15)
                nap(0.5)  # let the calendar redraw before locating the cell
                log(f"  advanced calendar {months_to_advance} month(s) to {current_date:%b %Y}")
            elif months_to_advance < 0:
                log(f"  WARNING: {current_date:%Y-%m-%d} is before today; "
                    "Telegram won't allow scheduling it.")

            # 4b. Compute and click the exact date cell.
            cx, cy = get_date_cell(current_date, cal_origin_x, cal_origin_y,
                                   cal_cell_w, cal_cell_h)
            log(f"  clicking {current_date:%b %d} at cell center ({cx}, {cy})")
            pyautogui.moveTo(cx, cy, duration=0.15)
            # Click first; the marker is drawn afterward so it cannot cover the
            # calendar and receive the click.
            pyautogui.click(cx, cy, button='left')
            show_click(cx, cy)
            nap(0.15)
            nap(0.2)
        else:
            # 4a (manual): User clicks the day by hand.
            log(f"[{day}/{total_messages}] Click the day yourself...")
            nap(1.0)

        # 5. Confirm the schedule
        pyautogui.press('enter')

        log(f"Scheduled {time_string}")
        show_scheduled(day, total_messages)
        current_date += timedelta(days=1)  # advance to the next day
        nap(0.15)  # Brief pause before the next loop starts


class SchedulerGUI:
    def __init__(self, root, log_queue):
        self.root = root
        self.log_queue = log_queue
        self.stop_event = threading.Event()
        self.worker = None
        self._setup_theme()

        root.title("Bulkmail Scheduler")
        root.configure(bg=BG)
        root.resizable(True, True)
        root.minsize(width=380, height=440)

        # --- State variables ---
        self.var_total = tk.IntVar(value=62)
        self.var_interval = tk.IntVar(value=3)
        self.var_typing_interval = tk.DoubleVar(value=0.12)
        self.var_year = tk.IntVar(value=2026)
        self.var_month = tk.IntVar(value=7)
        self.var_day = tk.IntVar(value=13)
        self.var_hour = tk.IntVar(value=22)
        self.var_minute = tk.IntVar(value=15)
        self.var_mode = tk.StringVar(value="auto")
        self.var_countdown = tk.DoubleVar(value=1.0)
        self.var_use_text = tk.BooleanVar(value=True)
        self.var_ox = tk.IntVar(value=771)
        self.var_oy = tk.IntVar(value=454)
        self.var_cw = tk.IntVar(value=63)
        self.var_ch = tk.IntVar(value=50)
        self.kb_listener = None

        # Calibration-by-click state (pynput listener).
        self.calib_clicks = None
        self._mouse_listener = None
        self._calibration_overlay = None
        self._click_marker = None

        tip = tk.Label(root,
                       text="ⓘ  Keep this window clear of the calendar  ·  F9 = emergency stop",
                       bg=BG, fg=MUTED, font=("Segoe UI", 8))
        tip.pack(fill="x", padx=10, pady=(6, 2))

        # One page, five sections: everything visible without tab switching.
        self._build_schedule_card()
        self._build_automation_card()
        self._build_message_card()
        self._build_log_area()
        self._build_action_bar()

        # Restore last-used settings (JSON) and keep them saved on close.
        self._load_settings()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._start_stop_hotkey()

        root.after(100, self.poll_log_queue)
        self._update_preview()

    # --- Theme ---
    def _setup_theme(self):
        """Dark, Telegram-inspired look built on the stylable 'clam' theme."""
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=CARD, foreground=FG, font=("Segoe UI", 9))
        style.configure("TFrame", background=CARD)
        style.configure("Card.TLabelframe", background=CARD, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, borderwidth=1)
        style.configure("Card.TLabelframe.Label", background=CARD,
                        foreground=ACCENT, font=("Segoe UI", 9, "bold"))
        style.configure("TLabel", background=CARD, foreground=FG)
        style.configure("Outer.TLabel", background=BG, foreground=MUTED)
        style.configure("Preview.TLabel", background=CARD, foreground=MUTED,
                        font=("Segoe UI", 8))
        style.configure("TSpinbox", fieldbackground=FIELD, background=FIELD,
                        foreground=FG, arrowcolor=FG, insertcolor=FG,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        style.map("TSpinbox", fieldbackground=[("readonly", FIELD)],
                  foreground=[("disabled", MUTED)])
        style.configure("TButton", background=FIELD, foreground=FG,
                        bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD)
        style.map("TButton",
                  background=[("active", "#43474e"), ("disabled", FIELD)],
                  foreground=[("disabled", MUTED)])
        style.configure("green.Horizontal.TProgressbar", troughcolor=FIELD,
                        background=GREEN, bordercolor=CARD,
                        lightcolor=GREEN, darkcolor=GREEN)

    def _spin(self, parent, var, lo, hi, width, increment=None, fmt=None):
        kw = {"from_": lo, "to": hi, "textvariable": var, "width": width}
        if increment is not None:
            kw["increment"] = increment
        if fmt:
            kw["format"] = fmt
        return ttk.Spinbox(parent, **kw)

    def _check_kwargs(self):
        """Consistent dark look for classic radio/check buttons."""
        return dict(bg=CARD, fg=FG, activebackground=CARD, activeforeground=FG,
                    selectcolor=FIELD, highlightthickness=0, bd=0,
                    cursor="hand2", font=("Segoe UI", 9))

    # --- Section builders ---
    def _build_schedule_card(self):
        card = ttk.Labelframe(self.root, text="  Schedule ",
                              style="Card.TLabelframe", padding=8)
        card.pack(fill="x", padx=8, pady=(2, 4))

        row1 = tk.Frame(card, bg=CARD)
        row1.pack(fill="x")
        ttk.Label(row1, text="Start").pack(side="left", padx=(0, 6))
        self._spin(row1, self.var_day, 1, 31, 3).pack(side="left", padx=1)
        ttk.Label(row1, text="·", foreground=MUTED).pack(side="left", padx=1)
        self._spin(row1, self.var_month, 1, 12, 3).pack(side="left", padx=1)
        ttk.Label(row1, text="·", foreground=MUTED).pack(side="left", padx=1)
        self._spin(row1, self.var_year, 2020, 2099, 5).pack(side="left", padx=1)
        ttk.Label(row1, text="at", foreground=MUTED).pack(side="left", padx=(8, 4))
        self._spin(row1, self.var_hour, 0, 23, 3).pack(side="left", padx=1)
        ttk.Label(row1, text=":", foreground=MUTED).pack(side="left", padx=1)
        self._spin(row1, self.var_minute, 0, 59, 3).pack(side="left", padx=1)

        row2 = tk.Frame(card, bg=CARD)
        row2.pack(fill="x", pady=(4, 0))
        ttk.Label(row2, text="Messages").pack(side="left", padx=(0, 6))
        self._spin(row2, self.var_total, 1, 999, 5).pack(side="left", padx=1)
        ttk.Label(row2, text="every", foreground=MUTED).pack(side="left", padx=(10, 4))
        self._spin(row2, self.var_interval, 1, 720, 4).pack(side="left", padx=1)
        ttk.Label(row2, text="min", foreground=MUTED).pack(side="left", padx=2)

        # Live first/last preview so the whole plan is visible before starting.
        self.preview_label = ttk.Label(card, text="", style="Preview.TLabel")
        self.preview_label.pack(fill="x", pady=(6, 0))
        for var in (self.var_total, self.var_interval, self.var_day,
                    self.var_month, self.var_year, self.var_hour,
                    self.var_minute):
            var.trace_add("write", self._update_preview)

    def _build_automation_card(self):
        card = ttk.Labelframe(self.root, text="  Automation ",
                              style="Card.TLabelframe", padding=8)
        card.pack(fill="x", padx=8, pady=(0, 4))

        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x")
        tk.Radiobutton(row, text="Auto-click calendar", variable=self.var_mode,
                       value="auto", **self._check_kwargs()).pack(side="left")
        tk.Radiobutton(row, text="Manual day", variable=self.var_mode,
                       value="manual", **self._check_kwargs()).pack(side="left", padx=(14, 0))

        row2 = tk.Frame(card, bg=CARD)
        row2.pack(fill="x", pady=(4, 0))
        ttk.Label(row2, text="Start delay").pack(side="left", padx=(0, 4))
        self._spin(row2, self.var_countdown, 0, 30, 4, increment=0.5,
                   fmt="%0.1f").pack(side="left", padx=1)
        ttk.Label(row2, text="s", foreground=MUTED).pack(side="left", padx=2)
        ttk.Label(row2, text="Typing speed").pack(side="left", padx=(16, 4))
        self._spin(row2, self.var_typing_interval, 0.01, 2, 5, increment=0.01,
                   fmt="%0.2f").pack(side="left", padx=1)
        ttk.Label(row2, text="s/char", foreground=MUTED).pack(side="left", padx=2)

        row3 = tk.Frame(card, bg=CARD)
        row3.pack(fill="x", pady=(4, 0))
        ttk.Label(row3, text="Grid").pack(side="left", padx=(0, 4))
        for label, var, lo, hi, w in [("O", self.var_ox, 0, 9999, 4),
                                      ("Y", self.var_oy, 0, 9999, 4),
                                      ("W", self.var_cw, 1, 999, 3),
                                      ("H", self.var_ch, 1, 999, 3)]:
            ttk.Label(row3, text=label, foreground=MUTED).pack(side="left", padx=(4, 1))
            self._spin(row3, var, lo, hi, w).pack(side="left", padx=1)
        ttk.Button(row3, text="Calibrate by click…",
                   command=self.start_calibrate).pack(side="left", padx=(10, 0))

    def _build_message_card(self):
        card = ttk.Labelframe(self.root, text="  Message ",
                              style="Card.TLabelframe", padding=8)
        card.pack(fill="x", padx=8, pady=(0, 4))
        hdr = tk.Frame(card, bg=CARD)
        hdr.pack(fill="x")
        ttk.Label(hdr, text="Optional - pasted before each schedule command",
                  foreground=MUTED).pack(side="left")
        self.use_msg_chk = tk.Checkbutton(hdr, text="Use this message",
                                          variable=self.var_use_text,
                                          **self._check_kwargs())
        self.use_msg_chk.pack(side="right")
        self.message_text = tk.Text(card, height=2, wrap="word", bd=0,
                                    highlightthickness=0, bg=FIELD, fg=FG,
                                    insertbackground=FG, font=("Segoe UI", 9))
        self.message_text.pack(fill="both", expand=True, pady=(4, 0))

    def _build_log_area(self):
        card = ttk.Labelframe(self.root, text="  Log ",
                              style="Card.TLabelframe", padding=8)
        card.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self.log_text = tk.Text(card, height=4, wrap="word", bd=0,
                                highlightthickness=0, bg=LOG_BG, fg=LOG_FG,
                                insertbackground=FG, font=("Consolas", 8),
                                state="disabled")
        scroll = tk.Scrollbar(card, command=self.log_text.yview,
                              troughcolor=FIELD, bg=CARD,
                              activebackground=BORDER, bd=0, width=10)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _build_action_bar(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=8, pady=(0, 2))
        self.btn_start = tk.Button(bar, text="▶  Start Scheduling",
                                   command=self.start, bg=GREEN, fg="white",
                                   activebackground="#258742",
                                   activeforeground="white", relief="flat",
                                   bd=0, padx=14, pady=4, cursor="hand2",
                                   disabledforeground="#6f8b76",
                                   font=("Segoe UI", 10, "bold"))
        self.btn_start.pack(side="left")
        self.btn_stop = tk.Button(bar, text="■  Stop", command=self.stop,
                                  state="disabled", bg=RED, fg="white",
                                  activebackground="#b32c2c",
                                  activeforeground="white", relief="flat",
                                  bd=0, padx=12, pady=4, cursor="hand2",
                                  disabledforeground="#8b6f6f",
                                  font=("Segoe UI", 10, "bold"))
        self.btn_stop.pack(side="left", padx=(8, 14))
        self.progress = ttk.Progressbar(bar, style="green.Horizontal.TProgressbar",
                                        maximum=1, value=0)
        self.progress.pack(side="left", fill="x", expand=True)

        foot = tk.Frame(self.root, bg=BG)
        foot.pack(fill="x", padx=8, pady=(0, 8))
        self.var_scheduled = tk.IntVar(value=0)
        self.scheduled_label = ttk.Label(foot, text="Scheduled: 0 / 0",
                                         style="Outer.TLabel")
        self.scheduled_label.pack(side="left")
        self.status_label = ttk.Label(foot, text="", style="Outer.TLabel",
                                      anchor="e")
        self.status_label.pack(side="right", fill="x", expand=True)

    # --- Live schedule preview ---
    def _update_preview(self, *_):
        """Show first/last message times computed from the GUI inputs."""
        try:
            start = datetime(self.var_year.get(), self.var_month.get(),
                             self.var_day.get(), self.var_hour.get(),
                             self.var_minute.get())
            total = self.var_total.get()
            interval = self.var_interval.get()
        except (ValueError, tk.TclError):
            self.preview_label.configure(text="⚠  Invalid start date/time",
                                         foreground="#ff6b6b")
            return
        # Matches schedule_messages exactly: the calendar advances one day per
        # message while the clock advances by the interval (wrapping at
        # midnight).
        last = start + timedelta(days=max(total - 1, 0))
        last_clock = start + timedelta(minutes=interval * max(total - 1, 0))
        last = last.replace(hour=last_clock.hour, minute=last_clock.minute)
        text = (f"First {start:%b %d, %H:%M}   →   Last {last:%b %d, %H:%M}"
                f"   ({total} × {interval} min)")
        if start < datetime.now():
            text = f"⚠  Start is in the past - Telegram will reject it  ·  {text}"
            self.preview_label.configure(text=text, foreground="#f2a33c")
        else:
            self.preview_label.configure(text=text, foreground=MUTED)

    # --- Logging via a thread-safe queue ---
    def log(self, msg):
        self.log_queue.put(msg)

    def poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", f"{msg}\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
                self._set_status(msg)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_log_queue)

    def _set_status(self, msg):
        """Mirror the latest log line next to the counter, colored by kind."""
        fg = MUTED
        if "ERROR" in msg:
            fg = "#ff6b6b"
        elif "WARNING" in msg:
            fg = "#f2a33c"
        elif msg.startswith("Scheduled ") or msg == "Finished.":
            fg = "#4fd07a"
        try:
            self.status_label.configure(text=msg[-90:], fg=fg)
        except tk.TclError:
            pass

    # --- Persistent JSON settings ---
    def _load_settings(self):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}

        self.var_total.set(data.get("total", 62))
        self.var_interval.set(data.get("interval", 3))
        self.var_typing_interval.set(data.get("typing_interval", 0.12))
        self.var_year.set(data.get("year", 2026))
        self.var_month.set(data.get("month", 7))
        self.var_day.set(data.get("day", 13))
        self.var_hour.set(data.get("hour", 22))
        self.var_minute.set(data.get("minute", 15))
        self.var_mode.set(data.get("mode", "auto"))
        self.var_countdown.set(data.get("countdown", 1))
        self.var_use_text.set(data.get("use_text", True))
        self.var_ox.set(data.get("grid_ox", 771))
        self.var_oy.set(data.get("grid_oy", 454))
        self.var_cw.set(data.get("grid_cw", 63))
        self.var_ch.set(data.get("grid_ch", 50))
        self.message_text.delete("1.0", "end")
        self.message_text.insert("1.0", data.get("message", ""))

        geom = data.get("geometry")
        if geom:
            try:
                self.root.geometry(geom)
            except tk.TclError:
                pass

    def _save_settings(self):
        data = {
            "total": self.var_total.get(),
            "interval": self.var_interval.get(),
            "typing_interval": self.var_typing_interval.get(),
            "year": self.var_year.get(),
            "month": self.var_month.get(),
            "day": self.var_day.get(),
            "hour": self.var_hour.get(),
            "minute": self.var_minute.get(),
            "mode": self.var_mode.get(),
            "countdown": self.var_countdown.get(),
            "use_text": self.var_use_text.get(),
            "message": self.message_text.get("1.0", "end").strip(),
            "grid_ox": self.var_ox.get(),
            "grid_oy": self.var_oy.get(),
            "grid_cw": self.var_cw.get(),
            "grid_ch": self.var_ch.get(),
            "geometry": self.root.geometry(),
        }
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError as exc:
            self.log(f"Could not save settings: {exc}")

    def on_close(self):
        if self._click_marker is not None and self._click_marker.winfo_exists():
            self._click_marker.destroy()
        self._save_settings()
        self.root.destroy()

    # --- Calibrate-by-click ---
    def start_calibrate(self):
        """Capture the calendar grid by clicking 3 cells instead of typing numbers."""
        if self.worker and self.worker.is_alive():
            self.log("Scheduling is running - stop it before calibrating.")
            return
        try:
            from pynput import mouse
        except ImportError:
            messagebox.showinfo("Missing dependency",
                                "pip install pynput  (needed for click-to-calibrate)")
            return

        self.calib_clicks = []
        self._create_calibration_overlay()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="disabled")
        self.log("CALIBRATE: click the TOP-LEFT calendar cell (Sun, week 1).")
        self.log("Then the cell to its RIGHT, then the cell BELOW it. 3 clicks total.")
        self._mouse_listener = mouse.Listener(
            on_click=self._on_click,
            on_move=None,
            on_scroll=None,
        )
        self._mouse_listener.start()

    def _create_calibration_overlay(self):
        """Create a transparent, always-on-top overlay showing calibration points."""
        overlay = tk.Toplevel(self.root)
        overlay.title("Calibration guide")
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.88)
        overlay.geometry("320x86+20+20")
        frame = tk.Frame(overlay, bg="#202124", padx=8, pady=6)
        frame.pack(fill="both", expand=True)
        self.calibration_label = tk.Label(
            frame, text="Calibration started", fg="white", bg="#202124",
            justify="left", anchor="w", font=("Segoe UI", 10),
        )
        self.calibration_label.pack(fill="both", expand=True)
        self._calibration_overlay = overlay

    def _update_calibration_overlay(self, text):
        overlay = self._calibration_overlay
        if overlay is not None and overlay.winfo_exists():
            self.calibration_label.configure(text=text)
            overlay.update_idletasks()

    def _close_calibration_overlay(self):
        overlay = self._calibration_overlay
        self._calibration_overlay = None
        if overlay is not None and overlay.winfo_exists():
            overlay.destroy()

    def _on_click(self, x, y, button, pressed):
        if pressed:
            self.calib_clicks.append((x, y))
            self.root.after(0, self._apply_calib_click)
        return True  # keep listening until explicitly stopped

    def _apply_calib_click(self):
        n = len(self.calib_clicks)
        if n == 1:
            x, y = self.calib_clicks[0]
            self.var_ox.set(x)
            self.var_oy.set(y)
            self._update_calibration_overlay(
                f"Captured 1/3: origin ({x}, {y})\\n"
                "Next: click the cell directly RIGHT of it."
            )
            self.log("  Click 1 -> origin set. Now click the cell to its RIGHT (same row).")
        elif n == 2:
            w = abs(self.calib_clicks[1][0] - self.calib_clicks[0][0])
            if w == 0:
                self.calib_clicks.pop()
                self._update_calibration_overlay("Same X detected.\\nClick a different cell to the RIGHT.")
                self.log("  Same X as first - click a DIFFERENT cell to the right.")
                return
            self.var_cw.set(w)
            self._update_calibration_overlay(
                f"Captured 2/3: cell width {w}px\\n"
                "Next: click the cell directly BELOW origin."
            )
            self.log(f"  Click 2 -> cell width {w}. Now click the cell BELOW (same column).")
        elif n == 3:
            h = abs(self.calib_clicks[2][1] - self.calib_clicks[0][1])
            if h == 0:
                self.calib_clicks.pop()
                self._update_calibration_overlay("Same Y detected.\\nClick a different cell BELOW.")
                self.log("  Same Y as first - click a DIFFERENT cell below.")
                return
            self.var_ch.set(h)
            self._update_calibration_overlay(
                f"Captured 3/3: cell height {h}px\\nCalibration complete."
            )
            self.log(f"  Click 3 -> cell height {h}. Calibration complete.")
            self._stop_calibrate()

    def _stop_calibrate(self):
        listener = self._mouse_listener
        self._mouse_listener = None
        self._close_calibration_overlay()
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass
        # Marshal all widget updates onto Tk's GUI thread.
        self.root.after(0, self._finish_calibration)

    def _finish_calibration(self):
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self._save_settings()
        self.log("Grid calibrated. Ready to Start.")

    # --- Run click marker ---
    def _update_scheduled_counter(self, scheduled, total):
        self.root.after(0, lambda: self._set_scheduled_counter(scheduled, total))

    def _set_scheduled_counter(self, scheduled, total):
        self.var_scheduled.set(scheduled)
        self.scheduled_label.configure(text=f"Scheduled: {scheduled} / {total}")
        try:
            self.progress.configure(maximum=max(total, 1), value=scheduled)
        except tk.TclError:
            pass

    def _show_click_marker(self, x, y):
        """Show a short-lived red dot at the exact automated click location."""
        def update_marker():
            if self._click_marker is not None and self._click_marker.winfo_exists():
                self._click_marker.destroy()
            marker = tk.Toplevel(self.root)
            marker.overrideredirect(True)
            marker.attributes("-topmost", True)
            marker.attributes("-alpha", 0.9)
            # The marker is visual only; it must never become the click target.
            # Make the overlay click-through on Windows where supported.
            try:
                marker.attributes("-transparentcolor", "red")
            except tk.TclError:
                pass
            size = 18
            marker.geometry(f"{size}x{size}+{int(x - size / 2)}+{int(y - size / 2)}")
            canvas = tk.Canvas(marker, width=size, height=size, bg="red",
                               highlightthickness=0)
            canvas.create_oval(1, 1, size - 1, size - 1, fill="red", outline="white", width=2)
            canvas.pack()
            self._click_marker = marker
            marker.after(650, lambda: self._hide_click_marker(marker))

        self.root.after(0, update_marker)

    def _hide_click_marker(self, marker):
        if marker.winfo_exists():
            marker.destroy()
        if self._click_marker is marker:
            self._click_marker = None

    # --- Start / Stop ---
    def start(self):
        if self.worker and self.worker.is_alive():
            self.log("A previous run is still stopping. Please wait a moment.")
            return
        try:
            base_time = datetime(self.var_year.get(), self.var_month.get(), self.var_day.get(),
                                 self.var_hour.get(), self.var_minute.get())
            total = self.var_total.get()
            interval = self.var_interval.get()
        except ValueError as exc:
            messagebox.showerror("Invalid date/time", str(exc))
            return

        # If a message was typed in the box, push it to the clipboard so the
        # loop's Ctrl+V pastes it. Leave it empty to reuse the current clipboard.
        if self.var_use_text.get():
            text = self.message_text.get("1.0", "end").strip()
            if text:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
                self.log("Copied message text to clipboard.")
            else:
                self.log("Message box empty - using current clipboard contents.")
        else:
            self.log("Using current clipboard contents as the message.")

        auto = (self.var_mode.get() == "auto")
        cal = (self.var_ox.get(), self.var_oy.get(),
               self.var_cw.get(), self.var_ch.get())

        self.stop_event.clear()
        self.var_scheduled.set(0)
        self.scheduled_label.configure(text=f"Scheduled: 0 / {self.var_total.get()}")
        try:
            self.progress.configure(maximum=max(total, 1), value=0)
        except tk.TclError:
            pass
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")

        countdown = self.var_countdown.get()
        self.log(f"Starting in {countdown}s. Switch to Telegram Desktop now!")

        def _run():
            try:
                # Interruptible countdown, so F9 works even before scheduling starts.
                deadline = time.time() + countdown
                while time.time() < deadline:
                    if self.stop_event.is_set():
                        self.log("Stopped before starting.")
                        return
                    time.sleep(0.02)
                schedule_messages(base_time, total, interval, auto, *cal,
                                  self.var_typing_interval.get(),
                                  self.stop_event, self.log, self._show_click_marker,
                                  self._update_scheduled_counter)
                self.log("Finished.")
            except _SchedulingStop:
                self.log("Stopped.")
            except Exception as exc:
                self.log(f"ERROR: {exc}")
            finally:
                # Always re-enable the buttons, even if the run crashed (e.g.
                # pyautogui failsafe, automation error, etc.).
                self.root.after(0, self.reset_buttons)

        self.worker = threading.Thread(target=_run, daemon=True)
        self.worker.start()
        self._save_settings()

    def stop(self):
        if not self.worker or not self.worker.is_alive():
            self.reset_buttons()
            return
        if self.stop_event.is_set():
            return
        self.log("Stop requested...")
        self.stop_event.set()
        # Restore the controls immediately; the worker will finish its current
        # PyAutoGUI call and then exit at its next interruptible checkpoint.
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")

    def reset_buttons(self):
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.worker = None

    def _start_stop_hotkey(self):
        """Watch for F9 anywhere on screen and abort a run instantly.

        Uses pynput (the same optional lib as click-calibration). If it's not
        installed, the corner-failsafe still works as a fallback.
        """
        try:
            from pynput import keyboard
        except ImportError:
            return

        def on_press(key):
            try:
                if key == keyboard.Key.f9:
                    self.stop()
            except Exception:
                pass

        try:
            listener = keyboard.Listener(on_press=on_press)
            listener.daemon = True
            listener.start()
            self.kb_listener = listener
        except Exception:
            self.kb_listener = None


def main():
    root = tk.Tk()
    log_queue = queue.Queue()
    SchedulerGUI(root, log_queue)
    root.mainloop()


if __name__ == "__main__":
    main()