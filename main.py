import json
import os
import queue
import sys
import threading
import time
import types
from datetime import datetime, timedelta

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, Signal


class _LazyPyAutoGUI:
    """Module-shaped placeholder so early reads don't trigger the slow import.

    The first real use (startup of the scheduler, calibration, or hotkey
    listener) replaces this with the real ``pyautogui`` module through
    ``_ensure_pyautogui()``.
    """

    def __getattr__(self, name):
        _ensure_pyautogui()
        return getattr(pyautogui, name)


class _PyAutoGUILazyWrapper:
    """Proxy that lets ``unittest.mock.patch.object`` swap a pyautogui method

    without triggering the slow real import. Attribute access is forwarded to
    the real module once it has been imported, and the wrapper keeps the
    module-level ``pyautogui.FAILSAFE`` attribute available at startup.
    """

    def __getattr__(self, name):
        if name == "FAILSAFE":
            return pyautogui.FAILSAFE
        _ensure_pyautogui()
        return getattr(pyautogui, name)

    def __setattr__(self, name, value):
        if name == "FAILSAFE":
            object.__setattr__(self, "FAILSAFE", value)
            return
        _ensure_pyautogui()
        setattr(pyautogui, name, value)

    def __delattr__(self, name):
        _ensure_pyautogui()
        delattr(pyautogui, name)

    def __call__(self, *args, **kwargs):
        _ensure_pyautogui()
        return pyautogui(*args, **kwargs)


def _ensure_pyautogui():
    """Import pyautogui on first real need so the GUI startup path is fast."""
    global pyautogui
    if not isinstance(pyautogui, types.ModuleType):
        import importlib
        real = importlib.import_module("pyautogui")
        pyautogui = real


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

# Qt counterpart of the Tk "clam" theme configured in the old GUI.
STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {FG};
    font-family: "Segoe UI";
    font-size: 9pt;
}}
QLabel {{ background: transparent; }}
QGroupBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 4px;
    margin-top: 11px;
    padding: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    color: {ACCENT};
    font-weight: bold;
}}
QLabel#Preview {{ color: {MUTED}; font-size: 8pt; }}
QLabel#Outer {{ color: {MUTED}; }}
QSpinBox, QDoubleSpinBox {{
    background: {FIELD};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 1px 3px;
}}
QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {MUTED}; }}
QPlainTextEdit {{
    background: {FIELD};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 3px;
}}
QPlainTextEdit#Log {{
    background: {LOG_BG};
    color: {LOG_FG};
    font-family: Consolas;
    font-size: 8pt;
}}
QCheckBox, QRadioButton {{ background: transparent; color: {FG}; spacing: 6px; }}
/* Explicit indicators: the native checked dot is invisible on this dark card. */
QCheckBox::indicator, QRadioButton::indicator {{
    width: 12px;
    height: 12px;
    border: 2px solid {MUTED};
    background: transparent;
}}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator {{ border-radius: 3px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    border-color: {ACCENT};
    background: {ACCENT};
}}
QPushButton {{
    background: {FIELD};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 3px 10px;
}}
QPushButton:hover {{ background: #43474e; }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton#Start {{
    background: {GREEN};
    color: white;
    font-weight: bold;
    padding: 5px 14px;
    border: none;
}}
QPushButton#Start:hover {{ background: #258742; }}
QPushButton#Start:disabled {{ background: #2b3a2f; color: #6f8b76; }}
QPushButton#Stop {{
    background: {RED};
    color: white;
    font-weight: bold;
    padding: 5px 12px;
    border: none;
}}
QPushButton#Stop:hover {{ background: #b32c2c; }}
QPushButton#Stop:disabled {{ background: #3a2b2b; color: #8b6f6f; }}
QProgressBar {{
    background: {FIELD};
    border: 1px solid {BORDER};
    border-radius: 4px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {GREEN}; border-radius: 3px; }}
QScrollBar:vertical {{ background: {CARD}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 20px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""

# --- FAILSAFE ---
# Moving your mouse to any corner of the screen will instantly stop the script!
pyautogui = _PyAutoGUILazyWrapper()
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
    # month navigation and is recomputed against the real "today" each run.
    today = datetime.now()
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


def _screen_ratio():
    """Device pixel ratio of the app's screen (1.0 when there is no screen)."""
    app = QtWidgets.QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return 1.0
    return screen.devicePixelRatio() or 1.0


def _physical_to_logical(x, y, ratio=None):
    """Convert pyautogui screen pixels to Qt's device-independent pixels.

    pyautogui (and therefore the calibrated calendar grid) measures in physical
    pixels, while Qt positions widgets in logical ones. On a scaled display the
    two differ by the device pixel ratio, which is what dragged the click ring
    down and to the right of the cell that was actually clicked.
    """
    ratio = _screen_ratio() if ratio is None else ratio
    return x / ratio, y / ratio


class _ClickMarker(QtWidgets.QWidget):
    """Short-lived, click-through ring drawn at the automated click spot."""

    SIZE = 18

    def __init__(self, x, y):
        super().__init__(
            None,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.resize(self.SIZE, self.SIZE)
        # (x, y) arrive in physical screen pixels; Qt moves windows in logical
        # pixels, so undo the display scaling first.
        logical_x, logical_y = _physical_to_logical(x, y)
        self.move(round(logical_x - self.SIZE / 2),
                  round(logical_y - self.SIZE / 2))

    def paintEvent(self, event):  # noqa: N802 (Qt naming)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        # Hollow ring: no fill, so the date cell underneath stays readable.
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QtGui.QPen(QtGui.QColor("white"), 2))
        inset = 2
        painter.drawEllipse(inset, inset, self.SIZE - 2 * inset, self.SIZE - 2 * inset)


class SchedulerGUI(QtWidgets.QWidget):
    # Worker-thread callbacks are marshalled onto the GUI thread through these.
    click_requested = Signal(int, int)
    scheduled_updated = Signal(int, int)
    reset_requested = Signal()
    stop_requested = Signal()
    calibration_clicked = Signal()

    def __init__(self, log_queue, parent=None):
        super().__init__(parent)
        self.log_queue = log_queue
        self.stop_event = threading.Event()
        self.worker = None
        self.kb_listener = None

        # Calibration-by-click state (pynput listener).
        self.calib_clicks = None
        self._mouse_listener = None
        self._calibration_overlay = None
        self._calibration_label = None
        self._click_marker = None

        self.setWindowTitle("Bulkmail Scheduler")
        self.setStyleSheet(STYLESHEET)
        self.resize(470, 630)
        self.setMinimumSize(380, 440)

        self._build_ui()
        self._connect_signals()

        # Restore last-used settings (JSON) and keep them saved on close.
        self._load_settings()
        self._start_stop_hotkey()

        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.timeout.connect(self.poll_log_queue)
        self._poll_timer.start(100)

        self._update_preview()

    # --- Widget helpers ---
    def _make_spin(self, parent, lo, hi, width, increment=1, decimals=0):
        """A compact, dark spin box sized roughly like the old char-width."""
        if decimals:
            box = QtWidgets.QDoubleSpinBox(parent)
            box.setDecimals(decimals)
            box.setSingleStep(increment)
        else:
            box = QtWidgets.QSpinBox(parent)
            box.setSingleStep(int(increment))
        box.setRange(lo, hi)
        box.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        box.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        box.setFixedWidth(20 + 7 * width)
        return box

    def _sep(self, parent, text):
        label = QtWidgets.QLabel(text, parent)
        label.setStyleSheet(f"color: {MUTED};")
        return label

    def _row(self, parent):
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        return layout

    # --- Section builders ---
    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 8)
        outer.setSpacing(4)

        tip = QtWidgets.QLabel(
            "ⓘ  Keep this window clear of the calendar  ·  F9 = emergency stop",
            self,
        )
        tip.setStyleSheet(f"color: {MUTED}; font-size: 8pt;")
        outer.addWidget(tip)

        # One page, five sections: everything visible without tab switching.
        self._build_schedule_card(outer)
        self._build_automation_card(outer)
        self._build_message_card(outer)
        self._build_log_area(outer)
        self._build_action_bar(outer)

    def _build_schedule_card(self, parent):
        card = QtWidgets.QGroupBox("  Schedule  ", self)
        box = QtWidgets.QVBoxLayout(card)
        box.setSpacing(6)

        row1 = self._row(card)
        row1.addWidget(QtWidgets.QLabel("Start", card))
        self.spin_day = self._make_spin(card, 1, 31, 3)
        self.spin_month = self._make_spin(card, 1, 12, 3)
        self.spin_year = self._make_spin(card, 2020, 2099, 5)
        self.spin_hour = self._make_spin(card, 0, 23, 3)
        self.spin_minute = self._make_spin(card, 0, 59, 3)
        for widget in (self.spin_day, self._sep(card, "·"), self.spin_month,
                       self._sep(card, "·"), self.spin_year):
            row1.addWidget(widget)
        row1.addWidget(self._sep(card, "at"))
        row1.addWidget(self.spin_hour)
        row1.addWidget(self._sep(card, ":"))
        row1.addWidget(self.spin_minute)
        row1.addStretch(1)
        box.addLayout(row1)

        row2 = self._row(card)
        row2.addWidget(QtWidgets.QLabel("Messages", card))
        self.spin_total = self._make_spin(card, 1, 999, 5)
        self.spin_interval = self._make_spin(card, 1, 720, 4)
        row2.addWidget(self.spin_total)
        row2.addWidget(self._sep(card, "every"))
        row2.addWidget(self.spin_interval)
        row2.addWidget(self._sep(card, "min"))
        row2.addStretch(1)
        box.addLayout(row2)

        # Live first/last preview so the whole plan is visible before starting.
        self.preview_label = QtWidgets.QLabel("", card)
        self.preview_label.setObjectName("Preview")
        self.preview_label.setWordWrap(True)
        box.addWidget(self.preview_label)

        parent.addWidget(card)

    def _build_automation_card(self, parent):
        card = QtWidgets.QGroupBox("  Automation  ", self)
        box = QtWidgets.QVBoxLayout(card)
        box.setSpacing(6)

        row1 = self._row(card)
        self.radio_auto = QtWidgets.QRadioButton("Auto-click calendar", card)
        self.radio_manual = QtWidgets.QRadioButton("Manual day", card)
        self.radio_auto.setChecked(True)
        mode_group = QtWidgets.QButtonGroup(card)
        mode_group.addButton(self.radio_auto)
        mode_group.addButton(self.radio_manual)
        self._mode_group = mode_group
        row1.addWidget(self.radio_auto)
        row1.addWidget(self.radio_manual)
        row1.addStretch(1)
        box.addLayout(row1)

        row2 = self._row(card)
        self.spin_countdown = self._make_spin(card, 0, 30, 4, increment=0.5, decimals=2)
        self.spin_typing = self._make_spin(card, 0.01, 2, 5, increment=0.01, decimals=2)
        row2.addWidget(QtWidgets.QLabel("Start delay", card))
        row2.addWidget(self.spin_countdown)
        row2.addWidget(self._sep(card, "s"))
        row2.addWidget(QtWidgets.QLabel("Typing speed", card))
        row2.addWidget(self.spin_typing)
        row2.addWidget(self._sep(card, "s/char"))
        row2.addStretch(1)
        box.addLayout(row2)

        row3 = self._row(card)
        row3.addWidget(QtWidgets.QLabel("Grid", card))
        self.spin_ox = self._make_spin(card, 0, 9999, 4)
        self.spin_oy = self._make_spin(card, 0, 9999, 4)
        self.spin_cw = self._make_spin(card, 1, 999, 3)
        self.spin_ch = self._make_spin(card, 1, 999, 3)
        for label, widget in (("O", self.spin_ox), ("Y", self.spin_oy),
                              ("W", self.spin_cw), ("H", self.spin_ch)):
            row3.addWidget(self._sep(card, label))
            row3.addWidget(widget)
        self.btn_calibrate = QtWidgets.QPushButton("Calibrate by click…", card)
        self.btn_calibrate.clicked.connect(self.start_calibrate)
        row3.addWidget(self.btn_calibrate)
        row3.addStretch(1)
        box.addLayout(row3)

        parent.addWidget(card)

    def _build_message_card(self, parent):
        card = QtWidgets.QGroupBox("  Message  ", self)
        box = QtWidgets.QVBoxLayout(card)
        box.setSpacing(6)

        hdr = self._row(card)
        hdr.addWidget(self._sep(card, "Optional - pasted before each schedule command"))
        hdr.addStretch(1)
        self.check_use_text = QtWidgets.QCheckBox("Use this message", card)
        self.check_use_text.setChecked(True)
        hdr.addWidget(self.check_use_text)
        box.addLayout(hdr)

        self.message_edit = QtWidgets.QPlainTextEdit(card)
        self.message_edit.setFixedHeight(50)
        box.addWidget(self.message_edit)

        parent.addWidget(card)

    def _build_log_area(self, parent):
        card = QtWidgets.QGroupBox("  Log  ", self)
        box = QtWidgets.QVBoxLayout(card)
        box.setSpacing(0)
        self.log_view = QtWidgets.QPlainTextEdit(card)
        self.log_view.setObjectName("Log")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(90)
        box.addWidget(self.log_view)
        parent.addWidget(card, 1)

    def _build_action_bar(self, parent):
        bar = self._row(self)
        self.btn_start = QtWidgets.QPushButton("▶  Start Scheduling", self)
        self.btn_start.setObjectName("Start")
        self.btn_start.clicked.connect(self.start)
        self.btn_stop = QtWidgets.QPushButton("■  Stop", self)
        self.btn_stop.setObjectName("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop)
        self.progress = QtWidgets.QProgressBar(self)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        bar.addWidget(self.btn_start)
        bar.addWidget(self.btn_stop)
        bar.addWidget(self.progress, 1)
        parent.addLayout(bar)

        foot = self._row(self)
        self.scheduled_label = QtWidgets.QLabel("Scheduled: 0 / 0", self)
        self.scheduled_label.setObjectName("Outer")
        self.status_label = QtWidgets.QLabel("", self)
        self.status_label.setObjectName("Outer")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        foot.addWidget(self.scheduled_label)
        foot.addStretch(1)
        foot.addWidget(self.status_label)
        parent.addLayout(foot)

    def _connect_signals(self):
        """Wire widget changes and cross-thread callbacks."""
        for var in (self.spin_total, self.spin_interval, self.spin_day,
                    self.spin_month, self.spin_year, self.spin_hour,
                    self.spin_minute):
            var.valueChanged.connect(self._update_preview)

        self.click_requested.connect(self._draw_click_marker)
        self.scheduled_updated.connect(self._set_scheduled_counter)
        self.reset_requested.connect(self.reset_buttons)
        self.stop_requested.connect(self.stop)
        self.calibration_clicked.connect(self._apply_calib_click)

    # --- Live schedule preview ---
    def _update_preview(self, *_):
        """Show first/last message times computed from the GUI inputs."""
        try:
            start = datetime(self.spin_year.value(), self.spin_month.value(),
                             self.spin_day.value(), self.spin_hour.value(),
                             self.spin_minute.value())
            total = self.spin_total.value()
            interval = self.spin_interval.value()
        except ValueError:
            self.preview_label.setStyleSheet("color: #ff6b6b;")
            self.preview_label.setText("⚠  Invalid start date/time")
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
            self.preview_label.setStyleSheet("color: #f2a33c;")
        else:
            self.preview_label.setStyleSheet(f"color: {MUTED};")
        self.preview_label.setText(text)

    # --- Logging via a thread-safe queue ---
    def log(self, msg):
        self.log_queue.put(msg)

    def poll_log_queue(self):
        scrolled = False
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_view.appendPlainText(msg)
                self._set_status(msg)
                scrolled = True
        except queue.Empty:
            pass
        if scrolled:
            scrollbar = self.log_view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _set_status(self, msg):
        """Mirror the latest log line next to the counter, colored by kind."""
        fg = MUTED
        if "ERROR" in msg:
            fg = "#ff6b6b"
        elif "WARNING" in msg:
            fg = "#f2a33c"
        elif msg.startswith("Scheduled ") or msg == "Finished.":
            fg = "#4fd07a"
        self.status_label.setStyleSheet(f"color: {fg};")
        self.status_label.setText(msg[-90:])

    # --- Mode radios ---
    def _mode(self):
        return "auto" if self.radio_auto.isChecked() else "manual"

    def _set_mode(self, mode):
        (self.radio_manual if mode == "manual" else self.radio_auto).setChecked(True)

    # --- Persistent JSON settings ---
    def _load_settings(self):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}

        self.spin_total.setValue(int(data.get("total", 62)))
        self.spin_interval.setValue(int(data.get("interval", 3)))
        self.spin_typing.setValue(float(data.get("typing_interval", 0.12)))
        self.spin_year.setValue(int(data.get("year", 2026)))
        self.spin_month.setValue(int(data.get("month", 7)))
        self.spin_day.setValue(int(data.get("day", 13)))
        self.spin_hour.setValue(int(data.get("hour", 22)))
        self.spin_minute.setValue(int(data.get("minute", 15)))
        self._set_mode(str(data.get("mode", "auto")))
        self.spin_countdown.setValue(float(data.get("countdown", 1)))
        self.check_use_text.setChecked(bool(data.get("use_text", True)))
        self.spin_ox.setValue(int(data.get("grid_ox", 771)))
        self.spin_oy.setValue(int(data.get("grid_oy", 454)))
        self.spin_cw.setValue(int(data.get("grid_cw", 63)))
        self.spin_ch.setValue(int(data.get("grid_ch", 50)))
        self.message_edit.setPlainText(str(data.get("message", "")))

        geom = data.get("geometry")
        if isinstance(geom, str) and geom:
            try:
                self.restoreGeometry(
                    QtCore.QByteArray.fromBase64(geom.encode("ascii")))
            except Exception:
                pass

    def _save_settings(self):
        data = {
            "total": self.spin_total.value(),
            "interval": self.spin_interval.value(),
            "typing_interval": self.spin_typing.value(),
            "year": self.spin_year.value(),
            "month": self.spin_month.value(),
            "day": self.spin_day.value(),
            "hour": self.spin_hour.value(),
            "minute": self.spin_minute.value(),
            "mode": self._mode(),
            "countdown": self.spin_countdown.value(),
            "use_text": self.check_use_text.isChecked(),
            "message": self.message_edit.toPlainText().strip(),
            "grid_ox": self.spin_ox.value(),
            "grid_oy": self.spin_oy.value(),
            "grid_cw": self.spin_cw.value(),
            "grid_ch": self.spin_ch.value(),
            "geometry": bytes(self.saveGeometry().toBase64()).decode("ascii"),
        }
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError as exc:
            self.log(f"Could not save settings: {exc}")

    def closeEvent(self, event):  # noqa: N802 (Qt naming)
        self._close_calibration_overlay()
        self._stop_mouse_listener()
        self._hide_click_marker()
        self._save_settings()
        if self.kb_listener is not None:
            try:
                self.kb_listener.stop()
            except Exception:
                pass
        self._poll_timer.stop()
        super().closeEvent(event)

    # --- Calibrate-by-click ---
    def start_calibrate(self):
        """Capture the calendar grid by clicking 3 cells instead of typing numbers."""
        if self.worker and self.worker.is_alive():
            self.log("Scheduling is running - stop it before calibrating.")
            return
        try:
            from pynput import mouse
        except ImportError:
            QtWidgets.QMessageBox.information(
                self, "Missing dependency",
                "pip install pynput  (needed for click-to-calibrate)")
            return

        self.calib_clicks = []
        self._create_calibration_overlay()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(False)
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
        overlay = QtWidgets.QWidget(
            None,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus,
        )
        overlay.setAttribute(Qt.WA_ShowWithoutActivating)
        overlay.setWindowOpacity(0.88)
        overlay.setStyleSheet("QWidget { background: #202124; }")
        overlay.resize(320, 86)
        overlay.move(20, 20)
        layout = QtWidgets.QVBoxLayout(overlay)
        layout.setContentsMargins(8, 6, 8, 6)
        label = QtWidgets.QLabel("Calibration started", overlay)
        label.setStyleSheet("color: white; font-size: 10pt;")
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        overlay.show()
        self._calibration_label = label
        self._calibration_overlay = overlay

    def _update_calibration_overlay(self, text):
        overlay = self._calibration_overlay
        if overlay is not None:
            self._calibration_label.setText(text)

    def _close_calibration_overlay(self):
        overlay = self._calibration_overlay
        self._calibration_overlay = None
        self._calibration_label = None
        if overlay is not None:
            overlay.close()
            overlay.deleteLater()

    def _on_click(self, x, y, button, pressed):
        if pressed:
            self.calib_clicks.append((x, y))
            self.calibration_clicked.emit()  # marshal onto the GUI thread
        return True  # keep listening until explicitly stopped

    def _apply_calib_click(self):
        n = len(self.calib_clicks)
        if n == 1:
            x, y = self.calib_clicks[0]
            self.spin_ox.setValue(x)
            self.spin_oy.setValue(y)
            self._update_calibration_overlay(
                f"Captured 1/3: origin ({x}, {y})\n"
                "Next: click the cell directly RIGHT of it."
            )
            self.log("  Click 1 -> origin set. Now click the cell to its RIGHT (same row).")
        elif n == 2:
            w = abs(self.calib_clicks[1][0] - self.calib_clicks[0][0])
            if w == 0:
                self.calib_clicks.pop()
                self._update_calibration_overlay("Same X detected.\nClick a different cell to the RIGHT.")
                self.log("  Same X as first - click a DIFFERENT cell to the right.")
                return
            self.spin_cw.setValue(w)
            self._update_calibration_overlay(
                f"Captured 2/3: cell width {w}px\n"
                "Next: click the cell directly BELOW origin."
            )
            self.log(f"  Click 2 -> cell width {w}. Now click the cell BELOW (same column).")
        elif n == 3:
            h = abs(self.calib_clicks[2][1] - self.calib_clicks[0][1])
            if h == 0:
                self.calib_clicks.pop()
                self._update_calibration_overlay("Same Y detected.\nClick a different cell BELOW.")
                self.log("  Same Y as first - click a DIFFERENT cell below.")
                return
            self.spin_ch.setValue(h)
            self._update_calibration_overlay(
                f"Captured 3/3: cell height {h}px\nCalibration complete."
            )
            self.log(f"  Click 3 -> cell height {h}. Calibration complete.")
            self._stop_calibrate()

    def _stop_mouse_listener(self):
        listener = self._mouse_listener
        self._mouse_listener = None
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass

    def _stop_calibrate(self):
        self._stop_mouse_listener()
        self._close_calibration_overlay()
        self._finish_calibration()

    def _finish_calibration(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._save_settings()
        self.log("Grid calibrated. Ready to Start.")

    # --- Run click marker ---
    def _update_scheduled_counter(self, scheduled, total):
        """Called from the worker thread; hops onto the GUI thread."""
        self.scheduled_updated.emit(scheduled, total)

    def _set_scheduled_counter(self, scheduled, total):
        self.scheduled_label.setText(f"Scheduled: {scheduled} / {total}")
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(scheduled)

    def _show_click_marker(self, x, y):
        """Called from the worker thread; hops onto the GUI thread."""
        self.click_requested.emit(int(x), int(y))

    def _draw_click_marker(self, x, y):
        """Show a short-lived red dot at the exact automated click location."""
        self._hide_click_marker()
        # The marker is visual only; it must never become the click target
        # (see WindowTransparentForInput in _ClickMarker).
        marker = _ClickMarker(x, y)
        marker.show()
        self._click_marker = marker
        QtCore.QTimer.singleShot(650, lambda: self._hide_click_marker(marker))

    def _hide_click_marker(self, marker=None):
        current = self._click_marker
        if current is not None and (marker is None or marker is current):
            current.close()
            current.deleteLater()
            self._click_marker = None

    # --- Start / Stop ---
    def start(self):
        if self.worker and self.worker.is_alive():
            self.log("A previous run is still stopping. Please wait a moment.")
            return
        try:
            base_time = datetime(self.spin_year.value(), self.spin_month.value(),
                                 self.spin_day.value(), self.spin_hour.value(),
                                 self.spin_minute.value())
            total = self.spin_total.value()
            interval = self.spin_interval.value()
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, "Invalid date/time", str(exc))
            return

        # If a message was typed in the box, push it to the clipboard so the
        # loop's Ctrl+V pastes it. Leave it empty to reuse the current clipboard.
        if self.check_use_text.isChecked():
            text = self.message_edit.toPlainText().strip()
            if text:
                QtWidgets.QApplication.clipboard().setText(text)
                self.log("Copied message text to clipboard.")
            else:
                self.log("Message box empty - using current clipboard contents.")
        else:
            self.log("Using current clipboard contents as the message.")

        auto = self.radio_auto.isChecked()
        cal = (self.spin_ox.value(), self.spin_oy.value(),
               self.spin_cw.value(), self.spin_ch.value())
        # Snapshot widget values on the GUI thread; the worker must not touch
        # Qt widgets.
        typing = self.spin_typing.value()
        countdown = self.spin_countdown.value()

        self.stop_event.clear()
        self.scheduled_label.setText(f"Scheduled: 0 / {total}")
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

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
                                  typing, self.stop_event, self.log,
                                  self._show_click_marker,
                                  self._update_scheduled_counter)
                self.log("Finished.")
            except _SchedulingStop:
                self.log("Stopped.")
            except Exception as exc:
                self.log(f"ERROR: {exc}")
            finally:
                # Always re-enable the buttons, even if the run crashed (e.g.
                # pyautogui failsafe, automation error, etc.).
                self.reset_requested.emit()

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
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def reset_buttons(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
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
                    # The listener thread must not touch widgets directly.
                    self.stop_requested.emit()
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
    app = QtWidgets.QApplication(sys.argv)
    log_queue = queue.Queue()
    window = SchedulerGUI(log_queue)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
