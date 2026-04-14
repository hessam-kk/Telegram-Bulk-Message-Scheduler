"""Regression suite for the Bulkmail Scheduler (main.py).

Everything here runs against the REAL code paths, but every mouse/keyboard
side effect is stubbed, so nothing on your screen is ever touched.

The suite is state-preserving by construction:
- main.py and settings.json are hashed before and after the run; if any test
  modified them the suite fails in tearDownModule.
- settings.json is only ever read.

Run with:
    python -m unittest discover -s tests -v
"""

import calendar
import contextlib
import hashlib
import inspect
import json
import os
import queue
import threading
import unittest
from datetime import datetime
from unittest import mock

import main  # safe: module-level code has an if __name__ == "__main__" guard

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PATH = os.path.join(ROOT, "main.py")
SETTINGS_PATH = os.path.join(ROOT, "settings.json")

# The calibration currently saved in settings.json (origin = center of the
# top-left calendar cell).
GRID = (770, 453, 62, 51)
TYPING = 0.12


# --------------------------------------------------------------------------
# State preservation guards
# --------------------------------------------------------------------------

_hashes_before = {}


def setUpModule():
    for path in (MAIN_PATH, SETTINGS_PATH):
        with open(path, "rb") as fh:
            _hashes_before[path] = hashlib.sha256(fh.read()).hexdigest()


def tearDownModule():
    """Fail the suite if any test modified the files under test."""
    for path, before in _hashes_before.items():
        with open(path, "rb") as fh:
            after = hashlib.sha256(fh.read()).hexdigest()
        if after != before:
            raise AssertionError(f"TEST RUN MODIFIED {path} - state not preserved!")


class _Recorder:
    """Callable that records every invocation instead of acting on the screen."""

    def __init__(self, name):
        self.name = name
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class _FixedNow:
    """Drop-in replacement for the datetime class used by schedule_messages.

    Only .now() is called inside schedule_messages; base_time arithmetic uses
    real datetime instances built by the tests.
    """

    fixed = None

    @classmethod
    def now(cls, tz=None):
        return cls.fixed


def run_schedule(base_time, total, interval, auto=True, fake_now=None,
                 typing=TYPING, preset_stop=False):
    """Run main.schedule_messages with all side effects stubbed out."""
    recs = {name: _Recorder(name)
            for name in ("hotkey", "press", "write", "moveTo", "click")}
    logs, clicks, counts = [], [], []
    stop = threading.Event()
    if preset_stop:
        stop.set()

    def show_click(x, y):
        clicks.append((x, y))

    def show_scheduled(n, t):
        counts.append((n, t))

    def log(msg):
        logs.append(msg)

    patches = [mock.patch.object(main.pyautogui, name, rec)
               for name, rec in recs.items()]
    if fake_now is not None:
        _FixedNow.fixed = fake_now
        patches.append(mock.patch.object(main, "datetime", _FixedNow))
    try:
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            try:
                main.schedule_messages(base_time, total, interval, auto, *GRID,
                                       typing, stop, log, show_click,
                                       show_scheduled)
                raised = None
            except main._SchedulingStop:
                raised = main._SchedulingStop
    finally:
        _FixedNow.fixed = None
    return {"recs": recs, "logs": logs, "clicks": clicks,
            "counts": counts, "raised": raised}


def presses_of(rec, key):
    """Return [(args, kwargs)] of press() calls for a given key name."""
    return [(a, k) for (a, k) in rec.calls if a and a[0] == key]


# --------------------------------------------------------------------------
# Pure calendar math
# --------------------------------------------------------------------------

class TestGetDateCell(unittest.TestCase):
    """Cell centers must match the real 2026 calendar layout."""

    def test_known_2026_cells(self):
        cases = {
            datetime(2026, 8, 1): (1142, 453),   # Saturday, first row (screenshot)
            datetime(2026, 9, 1): (894, 453),    # Tuesday, first row
            datetime(2026, 9, 7): (832, 504),    # user's start: Monday, row 1 col 1
            datetime(2026, 9, 8): (894, 504),
            datetime(2026, 9, 9): (956, 504),
            datetime(2026, 9, 30): (956, 657),   # last day, row 4 col 3
            datetime(2026, 10, 1): (1018, 453),  # next month, Thursday
            datetime(2026, 12, 10): (1018, 504),
        }
        for target, expected in cases.items():
            with self.subTest(date=target.date()):
                self.assertEqual(main.get_date_cell(target, *GRID), expected)

    def test_returns_integer_pixels(self):
        for day in range(1, 29):
            cell = main.get_date_cell(datetime(2026, 2, day), *GRID)
            self.assertTrue(all(isinstance(v, int) for v in cell))

    def test_all_2026_dates_stay_inside_the_6x7_grid(self):
        for month in range(1, 13):
            for day in range(1, calendar.monthrange(2026, month)[1] + 1):
                cx, cy = main.get_date_cell(datetime(2026, month, day), *GRID)
                col, row = (cx - GRID[0]) // GRID[2], (cy - GRID[1]) // GRID[3]
                self.assertTrue(0 <= col <= 6, f"col {col} out of grid {month}/{day}")
                self.assertTrue(0 <= row <= 5, f"row {row} out of grid {month}/{day}")


class TestMonthsBetween(unittest.TestCase):
    def test_user_scenario_next_month_day7(self):
        self.assertEqual(main.months_between(datetime(2026, 8, 30),
                                             datetime(2026, 9, 7)), 1)

    def test_same_month_is_zero(self):
        self.assertEqual(main.months_between(datetime(2026, 9, 1),
                                             datetime(2026, 9, 30)), 0)

    def test_backwards_is_negative(self):
        self.assertEqual(main.months_between(datetime(2026, 9, 1),
                                             datetime(2026, 7, 5)), -2)

    def test_year_boundary(self):
        self.assertEqual(main.months_between(datetime(2025, 12, 31),
                                             datetime(2026, 1, 1)), 1)

    def test_full_year(self):
        self.assertEqual(main.months_between(datetime(2025, 9, 1),
                                             datetime(2026, 9, 1)), 12)


# --------------------------------------------------------------------------
# schedule_messages end-to-end (side effects stubbed)
# --------------------------------------------------------------------------

class TestScheduleFlow(unittest.TestCase):
    def test_three_messages_starting_next_month_day7(self):
        """The user's exact scenario: Sep 7 2026 03:13, +3 min, from Aug 30."""
        out = run_schedule(datetime(2026, 9, 7, 3, 13), 3, 3,
                           fake_now=datetime(2026, 8, 30, 12, 0))
        recs, logs, clicks, counts = (out["recs"], out["logs"],
                                      out["clicks"], out["counts"])
        self.assertIsNone(out["raised"])

        # First message uses the exact start time, then +3 min each.
        self.assertEqual([c[0][0] for c in recs["write"].calls],
                         ["0313", "0316", "0319"])
        for _, kwargs in recs["write"].calls:
            self.assertEqual(kwargs.get("interval"), TYPING)

        # Time field is cleared with 4 backspaces at the typing interval.
        self.assertEqual(len(recs["write"].calls), 3)
        bs = presses_of(recs["press"], "backspace")
        self.assertEqual(len(bs), 3)
        for _, kwargs in bs:
            self.assertEqual(kwargs, {"presses": 4, "interval": TYPING})

        # Ctrl+V paste, dialog open, and confirm: once per message.
        self.assertEqual([c[0] for c in recs["hotkey"].calls],
                         [("ctrl", "v")] * 3)
        self.assertEqual(len(presses_of(recs["press"], "enter")), 6)
        self.assertEqual(len(presses_of(recs["press"], "tab")), 3)

        # Calendar reopens on today's month every loop: one Down each loop.
        downs = presses_of(recs["press"], "down")
        self.assertEqual(len(downs), 3)
        for _, kwargs in downs:
            self.assertEqual(kwargs, {"presses": 1, "interval": 0.15})
        self.assertEqual(sum("advanced calendar" in m for m in logs), 3)

        # Sep 7/8/9 click the correct cell centers, marker after click.
        self.assertEqual([c[0][:2] for c in recs["moveTo"].calls],
                         [(832, 504), (894, 504), (956, 504)])
        self.assertEqual([(c[0][0], c[0][1]) for c in recs["click"].calls],
                         [(832, 504), (894, 504), (956, 504)])
        for _, kwargs in recs["click"].calls:
            self.assertEqual(kwargs, {"button": "left"})
        self.assertEqual(clicks, [(832, 504), (894, 504), (956, 504)])

        # Counter reports 1/3, 2/3, 3/3.
        self.assertEqual(counts, [(1, 3), (2, 3), (3, 3)])

        # The loop dates advance one day at a time from the GUI start date.
        self.assertTrue(any("2026-09-07" in m for m in logs))
        self.assertTrue(any("2026-09-08" in m for m in logs))
        self.assertTrue(any("2026-09-09" in m for m in logs))

    def test_same_month_needs_no_month_advance(self):
        out = run_schedule(datetime(2026, 9, 5, 9, 0), 1, 5,
                           fake_now=datetime(2026, 9, 1))
        self.assertEqual(presses_of(out["recs"]["press"], "down"), [])
        self.assertFalse(any("advanced calendar" in m for m in out["logs"]))
        self.assertEqual([(c[0][0], c[0][1]) for c in out["recs"]["click"].calls],
                         [(1142, 453)])  # Sep 5 -> row 0, Saturday

    def test_multi_month_advance_presses_down_n_times(self):
        out = run_schedule(datetime(2026, 12, 10, 8, 0), 1, 5,
                           fake_now=datetime(2026, 9, 1))
        downs = presses_of(out["recs"]["press"], "down")
        self.assertEqual(len(downs), 1)
        self.assertEqual(downs[0][1], {"presses": 3, "interval": 0.15})
        self.assertEqual([(c[0][0], c[0][1]) for c in out["recs"]["click"].calls],
                         [(1018, 504)])

    def test_month_boundary_crossing_midrun(self):
        """Sep 30 -> Oct 1: month advance is recomputed per message."""
        out = run_schedule(datetime(2026, 9, 30, 3, 13), 2, 3,
                           fake_now=datetime(2026, 9, 1))
        downs = presses_of(out["recs"]["press"], "down")
        self.assertEqual([k.get("presses") for _, k in downs], [1])
        self.assertEqual([(c[0][0], c[0][1]) for c in out["recs"]["click"].calls],
                         [(956, 657),   # Sep 30
                          (1018, 453)])  # Oct 1

    def test_past_date_warns_and_still_clicks(self):
        out = run_schedule(datetime(2026, 7, 5, 3, 13), 1, 3,
                           fake_now=datetime(2026, 9, 1))
        self.assertEqual(presses_of(out["recs"]["press"], "down"), [])
        self.assertTrue(any("WARNING" in m for m in out["logs"]))
        self.assertEqual([(c[0][0], c[0][1]) for c in out["recs"]["click"].calls],
                         [(770, 504)])  # Jul 5 -> row 1, Sunday

    def test_manual_mode_skips_clicking_but_still_counts(self):
        out = run_schedule(datetime(2026, 9, 7, 3, 13), 1, 3, auto=False,
                           fake_now=datetime(2026, 8, 30))
        self.assertEqual(out["recs"]["moveTo"].calls, [])
        self.assertEqual(out["recs"]["click"].calls, [])
        self.assertEqual(out["clicks"], [])
        self.assertTrue(any("Click the day yourself" in m for m in out["logs"]))
        self.assertEqual(out["counts"], [(1, 1)])

    def test_stop_before_start_aborts_with_no_actions(self):
        out = run_schedule(datetime(2026, 9, 7, 3, 13), 3, 3, preset_stop=True)
        self.assertIs(out["raised"], main._SchedulingStop)
        for rec in out["recs"].values():
            self.assertEqual(rec.calls, [])


# --------------------------------------------------------------------------
# Module-level invariants
# --------------------------------------------------------------------------

class TestModuleState(unittest.TestCase):
    def test_main_compiles(self):
        with open(MAIN_PATH, "r", encoding="utf-8") as fh:
            source = fh.read()
        compile(source, "main.py", "exec")  # raises on any syntax breakage

    def test_settings_path_sits_next_to_main(self):
        self.assertEqual(main.SETTINGS_PATH, SETTINGS_PATH)

    def test_failsafe_stays_enabled(self):
        self.assertTrue(main.pyautogui.FAILSAFE)

    def test_schedule_signature_matches_gui_wiring(self):
        expected = ["base_time", "total_messages", "interval_minutes",
                    "auto_click", "cal_origin_x", "cal_origin_y",
                    "cal_cell_w", "cal_cell_h", "typing_interval",
                    "stop_event", "log", "show_click", "show_scheduled"]
        actual = list(inspect.signature(main.schedule_messages).parameters)
        self.assertEqual(actual, expected)


class TestSettingsSnapshot(unittest.TestCase):
    """settings.json is read-only here; the values below are the current ones."""

    def test_settings_json_parses_and_matches_current_state(self):
        with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        expected = {
            # Snapshot of the current settings. If you intentionally change
            # settings in the GUI, update these to the new values.
            "total": 93, "interval": 3, "typing_interval": 0.07,
            "year": 2026, "month": 9, "day": 7,
            "hour": 3, "minute": 25, "mode": "auto", "countdown": 0.25,
            "use_text": True,
            "grid_ox": 770, "grid_oy": 453, "grid_cw": 62, "grid_ch": 51,
        }
        for key, value in expected.items():
            self.assertEqual(data.get(key), value, key)


# --------------------------------------------------------------------------
# GUI smoke test (no window shown, nothing saved)
# --------------------------------------------------------------------------

class TestGuiSmoke(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
            self.root = tk.Tk()
        except Exception as exc:  # headless box -> skip GUI checks
            self.skipTest(f"Tk unavailable: {exc}")
        self.root.withdraw()
        self.gui = main.SchedulerGUI(self.root, queue.Queue())

    def tearDown(self):
        self.root.destroy()

    def _settings(self):
        with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def test_gui_loads_current_settings(self):
        data = self._settings()
        self.assertEqual(self.gui.var_total.get(), data["total"])
        self.assertEqual(self.gui.var_interval.get(), data["interval"])
        self.assertAlmostEqual(self.gui.var_typing_interval.get(),
                               data["typing_interval"])
        self.assertEqual(self.gui.var_year.get(), data["year"])
        self.assertEqual(self.gui.var_month.get(), data["month"])
        self.assertEqual(self.gui.var_day.get(), data["day"])
        self.assertEqual(self.gui.var_hour.get(), data["hour"])
        self.assertEqual(self.gui.var_minute.get(), data["minute"])
        self.assertEqual(self.gui.var_mode.get(), data["mode"])
        self.assertEqual(self.gui.var_ox.get(), data["grid_ox"])
        self.assertEqual(self.gui.var_oy.get(), data["grid_oy"])
        self.assertEqual(self.gui.var_cw.get(), data["grid_cw"])
        self.assertEqual(self.gui.var_ch.get(), data["grid_ch"])

    def test_countdown_accepts_half_seconds(self):
        self.gui.var_countdown.set(0.5)
        self.assertEqual(self.gui.var_countdown.get(), 0.5)

    def test_typing_interval_accepts_fine_steps(self):
        self.gui.var_typing_interval.set(0.05)
        self.assertEqual(self.gui.var_typing_interval.get(), 0.05)

    def test_scheduled_counter_updates(self):
        self.gui._set_scheduled_counter(5, 94)
        self.assertEqual(self.gui.var_scheduled.get(), 5)
        self.assertEqual(self.gui.scheduled_label.cget("text"),
                         "Scheduled: 5 / 94")
        self.assertEqual(self.gui.progress["value"], 5)
        self.assertEqual(self.gui.progress["maximum"], 94)

    def test_live_preview_matches_current_plan(self):
        # settings.json: Sep 7 2026 03:25, 93 messages, every 3 min.
        # One calendar day per message + interval on the clock: last = Dec 8.
        text = self.gui.preview_label.cget("text")
        self.assertIn("First Sep 07, 03:25", text)
        self.assertIn("Last Dec 08, 08:01", text)
        self.assertIn("(93 × 3 min)", text)

    def test_live_preview_rejects_impossible_dates(self):
        self.gui.var_month.set(13)
        self.assertIn("Invalid", self.gui.preview_label.cget("text"))
        self.gui.var_month.set(2)
        self.gui.var_day.set(31)
        self.assertIn("Invalid", self.gui.preview_label.cget("text"))


if __name__ == "__main__":
    unittest.main()
