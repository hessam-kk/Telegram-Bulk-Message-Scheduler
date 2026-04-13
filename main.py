import queue
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

import pyautogui

# --- FAILSAFE ---
# Moving your mouse to any corner of the screen will instantly stop the script!
pyautogui.FAILSAFE = True


def get_date_cell(target_date, origin_x, origin_y, cell_w, cell_h):
    """Return the (x, y) pixel coordinates of the center of `target_date`'s cell.

    The calendar must currently be showing `target_date`'s month. The grid is
    7 columns wide (Sunday first) x 6 rows tall.
    """
    # Column of the 1st of the month: Sunday=0, Monday=1, ..., Saturday=6.
    first_day_col = (target_date.replace(day=1).weekday() + 1) % 7

    # Position of `target_date` within the 42-cell (0-41) grid.
    cell_index = first_day_col + target_date.day - 1
    row, col = divmod(cell_index, 7)

    return (
        origin_x + col * cell_w + cell_w // 2,
        origin_y + row * cell_h + cell_h // 2,
    )


def schedule_messages(base_time, total_messages, interval_minutes, auto_click,
                      cal_origin_x, cal_origin_y, cal_cell_w, cal_cell_h,
                      stop_event, log):
    """Runs the scheduling loop. `log` is a callable(msg) for progress output."""
    log("Starting in 1 second. Switch to Telegram Desktop and do not touch your mouse!")
    log("FAILSAFE IS ON: Slam your mouse into any corner of the screen to panic-stop.")
    time.sleep(1)

    # Telegram's calendar opens on the current month, so this is the anchor for
    # month navigation and is recomputed against the real "today" each run.
    today = datetime.now()
    # The date of the first scheduled message; each next message is a day later.
    current_date = base_time.replace(hour=0, minute=0, second=0, microsecond=0)

    for day in range(1, total_messages + 1):
        if stop_event.is_set():
            log("Stopped by user.")
            return

        # 1. Paste the command
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.2)

        # 2. Open the schedule dialog
        pyautogui.press('enter')
        time.sleep(0.3)

        # Calculate the new time (shifting the clock forward by interval per loop)
        run_time = base_time + timedelta(minutes=interval_minutes * day)
        time_string = run_time.strftime('%H%M')
        log(f"[{day}/{total_messages}] Scheduling {current_date:%Y-%m-%d} at {time_string}")

        # 3. Type the calculated time into the time input box
        pyautogui.press('backspace', presses=4, interval=0.05)  # Clear old time just in case
        pyautogui.write(time_string)
        time.sleep(0.1)

        # 4. Focus the date picker / calendar.
        pyautogui.press('tab')
        time.sleep(0.2)

        if auto_click:
            # 4a. Advance to the correct month. The picker reopens on today's
            # month for every message, so recompute the offset each loop.
            months_to_advance = (
                (current_date.year - today.year) * 12
                + (current_date.month - today.month)
            )
            if months_to_advance > 0:
                pyautogui.press('down', presses=months_to_advance, interval=0.1)
                time.sleep(0.3)  # give the UI time to switch months
            elif months_to_advance < 0:
                log(f"  WARNING: {current_date:%Y-%m-%d} is before today; "
                    "Telegram won't allow scheduling it.")

            # 4b. Compute and click the exact date cell.
            cx, cy = get_date_cell(current_date, cal_origin_x, cal_origin_y,
                                   cal_cell_w, cal_cell_h)
            pyautogui.moveTo(cx, cy)
            time.sleep(0.1)
            pyautogui.click(button='left')
            time.sleep(0.2)
        else:
            # 4a (manual): User clicks the day by hand.
            log(f"[{day}/{total_messages}] Please manually click the day on the calendar now...")
            time.sleep(1.0)

        # 5. Confirm the schedule
        pyautogui.press('enter')

        log(f"Scheduled message with time: {time_string}")
        current_date += timedelta(days=1)  # advance to the next day
        time.sleep(0.15)  # Brief pause before the next loop starts


class SchedulerGUI:
    def __init__(self, root, log_queue):
        self.root = root
        self.log_queue = log_queue
        self.stop_event = threading.Event()
        self.worker = None

        root.title("Telegram Bulk Message Scheduler")
        root.resizable(False, False)
        root.configure(padx=16, pady=16)

        # --- Intro ---
        intro = ("Copy the message to your clipboard, open Telegram Desktop,\n"
                 "and place your cursor in the message input box before starting.")
        tk.Label(root, text=intro, justify="left", anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        # --- Config inputs ---
        self.var_total = tk.IntVar(value=62)
        self.var_interval = tk.IntVar(value=3)
        self.var_year = tk.IntVar(value=2026)
        self.var_month = tk.IntVar(value=7)
        self.var_day = tk.IntVar(value=13)
        self.var_hour = tk.IntVar(value=22)
        self.var_minute = tk.IntVar(value=15)
        self.var_mode = tk.StringVar(value="auto")
        self.var_countdown = tk.IntVar(value=1)
        self.var_use_text = tk.BooleanVar(value=True)

        # --- Message text box (optional; copied to clipboard on Start) ---
        msg = ttk.LabelFrame(root, text="Message text (optional)")
        msg.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.message_text = tk.Text(msg, height=3, width=72, wrap="word")
        self.message_text.pack(side="top", fill="both", expand=True, padx=8, pady=(6, 2))
        ttk.Checkbutton(
            msg,
            text="Use the text above as the message (copied to clipboard on Start)",
            variable=self.var_use_text,
        ).pack(side="left", padx=8, pady=(0, 6))
        tk.Label(msg, text="Leave blank to use whatever is already in your clipboard.",
                 fg="gray").pack(side="right", padx=8, pady=(0, 6))

        form = ttk.Frame(root)
        form.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(form, text="Total messages:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Spinbox(form, from_=1, to=999, textvariable=self.var_total, width=6).grid(
            row=0, column=1, sticky="w", pady=2)
        ttk.Label(form, text="Interval (min):").grid(row=0, column=2, sticky="w", padx=(16, 6), pady=2)
        ttk.Spinbox(form, from_=1, to=720, textvariable=self.var_interval, width=6).grid(
            row=0, column=3, sticky="w", pady=2)

        ttk.Label(form, text="Start datetime:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=2)
        date = ttk.Frame(form)
        date.grid(row=1, column=1, columnspan=3, sticky="w", pady=2)
        ttk.Spinbox(date, from_=1, to=31, textvariable=self.var_day, width=3).pack(side="left")
        ttk.Label(date, text="/").pack(side="left")
        ttk.Spinbox(date, from_=1, to=12, textvariable=self.var_month, width=3).pack(side="left")
        ttk.Label(date, text="/").pack(side="left")
        ttk.Spinbox(date, from_=2020, to=2099, textvariable=self.var_year, width=5).pack(side="left")
        ttk.Label(date, text="  ").pack(side="left")
        ttk.Spinbox(date, from_=0, to=23, textvariable=self.var_hour, width=3).pack(side="left")
        ttk.Label(date, text=":").pack(side="left")
        ttk.Spinbox(date, from_=0, to=59, textvariable=self.var_minute, width=3).pack(side="left")

        # --- Calendar calibration + mode ---
        cal = ttk.LabelFrame(root, text="Calendar auto-click (screen pixels)")
        cal.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self.var_ox = tk.IntVar(value=771)
        self.var_oy = tk.IntVar(value=454)
        self.var_cw = tk.IntVar(value=63)
        self.var_ch = tk.IntVar(value=50)

        ttk.Label(cal, text="Origin X:").grid(row=0, column=0, sticky="w", padx=(8, 4), pady=2)
        ttk.Spinbox(cal, from_=0, to=9999, textvariable=self.var_ox, width=6).grid(
            row=0, column=1, sticky="w", pady=2)
        ttk.Label(cal, text="Origin Y:").grid(row=0, column=2, sticky="w", padx=(16, 4), pady=2)
        ttk.Spinbox(cal, from_=0, to=9999, textvariable=self.var_oy, width=6).grid(
            row=0, column=3, sticky="w", pady=2)
        ttk.Label(cal, text="Cell W:").grid(row=0, column=4, sticky="w", padx=(16, 4), pady=2)
        ttk.Spinbox(cal, from_=1, to=999, textvariable=self.var_cw, width=6).grid(
            row=0, column=5, sticky="w", pady=2)
        ttk.Label(cal, text="Cell H:").grid(row=0, column=6, sticky="w", padx=(16, 4), pady=2)
        ttk.Spinbox(cal, from_=1, to=999, textvariable=self.var_ch, width=6).grid(
            row=0, column=7, sticky="w", pady=2)

        tk.Label(cal, text="Origin = top-left of the first cell (Sun of week 1).",
                 fg="gray").grid(row=1, column=0, columnspan=8, sticky="w", padx=8, pady=(0, 2))

        tk.Radiobutton(cal, text="Auto-click date (uses grid above)",
                       variable=self.var_mode, value="auto").grid(
            row=2, column=0, columnspan=4, sticky="w", padx=8)
        tk.Radiobutton(cal, text="Pause & let me click the day",
                       variable=self.var_mode, value="manual").grid(
            row=2, column=4, columnspan=4, sticky="w", padx=8)

        ttk.Label(form, text="Countdown (s):").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Spinbox(form, from_=0, to=30, textvariable=self.var_countdown, width=6).grid(
            row=3, column=1, sticky="w", pady=2)

        # --- Buttons ---
        buttons = ttk.Frame(root)
        buttons.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.btn_start = ttk.Button(buttons, text="Start Scheduling", command=self.start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(buttons, text="Stop", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=(8, 0))

        # --- Log panel ---
        log_frame = ttk.Frame(root)
        log_frame.grid(row=5, column=0, columnspan=2, sticky="nsew")
        self.log_text = tk.Text(log_frame, height=14, width=72, state="disabled", wrap="word")
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        root.grid_rowconfigure(5, weight=1)
        root.after(100, self.poll_log_queue)

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
        except queue.Empty:
            pass
        self.root.after(100, self.poll_log_queue)

    # --- Start / Stop ---
    def start(self):
        if self.worker and self.worker.is_alive():
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
                self.log("Message box is empty - using current clipboard contents.")
        else:
            self.log("Using current clipboard contents as the message.")

        auto = (self.var_mode.get() == "auto")
        cal = (self.var_ox.get(), self.var_oy.get(),
               self.var_cw.get(), self.var_ch.get())

        self.stop_event.clear()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")

        countdown = self.var_countdown.get()
        if countdown > 0:
            self.log(f"Starting in {countdown}s. Switch to Telegram Desktop now!")
        else:
            self.log("Starting now. Switch to Telegram Desktop!")

        def _run():
            time.sleep(countdown)
            schedule_messages(base_time, total, interval, auto, *cal,
                              self.stop_event, self.log)
            self.log("Finished.")
            self.root.after(0, self.reset_buttons)

        self.worker = threading.Thread(target=_run, daemon=True)
        self.worker.start()

    def stop(self):
        if self.stop_event.is_set():
            return
        self.log("Stop requested...")
        self.stop_event.set()

    def reset_buttons(self):
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")


def main():
    root = tk.Tk()
    log_queue = queue.Queue()
    SchedulerGUI(root, log_queue)
    root.mainloop()


if __name__ == "__main__":
    main()