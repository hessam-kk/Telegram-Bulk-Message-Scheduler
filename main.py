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


def schedule_messages(base_time, total_messages, interval_minutes,
                      manual_day_select, stop_event, log):
    """Runs the scheduling loop. `log` is a callable(msg) for progress output."""
    log("Starting in 1 second. Switch to Telegram Desktop and do not touch your mouse!")
    log("FAILSAFE IS ON: Slam your mouse into any corner of the screen to panic-stop.")
    time.sleep(1)

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

        # 3. Type the calculated time into the time input box
        pyautogui.press('backspace', presses=4, interval=0.05)  # Clear old time just in case
        log(f'writing time: {time_string}')
        pyautogui.write(time_string)

        # 4. --- MANUAL DATE SELECTION ---
        # Tab to the calendar, then use a crude "skip months" heuristic.
        pyautogui.press('tab')
        if day >= 29:
            pyautogui.press('down')
        if day >= 57:
            pyautogui.press('down')

        if manual_day_select:
            log(f"[{day}/{total_messages}] Please manually click the day on the calendar now...")
            time.sleep(1.0)  # Gives you 1 second to click the correct date.

        # 5. Confirm the schedule
        pyautogui.press('enter')

        log(f"Scheduled message with time: {time_string}")
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
        self.var_total = tk.IntVar(value=58)
        self.var_interval = tk.IntVar(value=3)
        self.var_year = tk.IntVar(value=2025)
        self.var_month = tk.IntVar(value=10)
        self.var_day = tk.IntVar(value=15)
        self.var_hour = tk.IntVar(value=20)
        self.var_minute = tk.IntVar(value=0)
        self.var_manual = tk.BooleanVar(value=True)
        self.var_countdown = tk.IntVar(value=1)

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

        ttk.Label(form, text="Countdown (s):").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Spinbox(form, from_=0, to=30, textvariable=self.var_countdown, width=6).grid(
            row=2, column=1, sticky="w", pady=2)
        ttk.Checkbutton(form, text="Pause for manual day click",
                        variable=self.var_manual).grid(row=2, column=2, columnspan=2,
                                                       sticky="w", padx=(16, 0), pady=2)

        # --- Buttons ---
        buttons = ttk.Frame(root)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.btn_start = ttk.Button(buttons, text="Start Scheduling", command=self.start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(buttons, text="Stop", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=(8, 0))

        # --- Log panel ---
        log_frame = ttk.Frame(root)
        log_frame.grid(row=3, column=0, columnspan=2, sticky="nsew")
        self.log_text = tk.Text(log_frame, height=14, width=64, state="disabled", wrap="word")
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        root.grid_rowconfigure(3, weight=1)
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
            schedule_messages(base_time, total, interval,
                              self.var_manual.get(), self.stop_event, self.log)
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