# Telegram Bulk Message Scheduler 🚀

A Python-based automation tool to rapidly schedule large batches of messages on Telegram Desktop.

## 📌 Overview
This script automates the tedious process of scheduling messages. It is particularly useful for bot commands, daily reminders, or marketing posts that need to be spread out over several days or weeks.

## ✨ Features
- **Auto-Incrementing Time:** Automatically shifts the clock forward (default: 3 minutes) for every message.
- **Calendar Navigation:** Logic to handle multi-week scheduling by simulating "Down" arrow presses to reach future dates.
- **Fail-Safe:** Built-in emergency stop (move mouse to any screen corner).
- **Customizable:** Easily adjust the start date, total message count, and intervals.

## 🛠 Prerequisites
1. **Python 3.x** installed.
2. **Telegram Desktop** (The script interacts with the UI of the desktop app).
3. **System Language:** Ensure your system keyboard layout is set to **English**.

## 🚀 Getting Started

### 1. Install Dependencies
```bash
pip install pyautogui
```

### 2. Configuration
Open `main.py` and adjust the following variables:
* `total_messages`: How many messages you want to schedule.
* `base_time`: The starting date and time for your first scheduled message.
```python
base_time = datetime(2025, 10, 15, 20, 00) # Year, Month, Day, Hour, Minute
```

### 3. Usage
1. **Copy** the text you want to schedule to your clipboard (Ctrl+C).
2. Open the chat in **Telegram Desktop**.
3. Run the script:
   ```bash
   python main.py
   ```
4. **Immediately** switch back to Telegram Desktop and place your cursor in the message input box.
5. **Watch the Magic:** The script will paste, open the schedule menu, type the time, and click the buttons.
   * *Note: For date selection, the script pauses briefly and uses 'Down' arrow logic to select future dates.*

## ⚠️ Important Warnings
- **Do not move the mouse** while the script is running unless you want to trigger the Failsafe.
- **UI Dependency:** This script relies on keyboard shortcuts and UI focus. If you click away from Telegram, the script will continue typing into whatever window is active.
- **Calibration:** Depending on your PC speed, you may need to adjust the `time.sleep()` values to ensure Telegram's UI keeps up with the script.

## ⚖️ License
This project is for educational and personal productivity purposes. Use responsibly and in accordance with Telegram's Terms of Service.
