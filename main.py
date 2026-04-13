import pyautogui
import time
from datetime import datetime, timedelta

# --- FAILSAFE ---
# Moving your mouse to any corner of the screen will instantly stop the script!
pyautogui.FAILSAFE = True 

# --- YOUR CONFIGURATION ---
total_messages = 58
# Note: Make sure "🎲 گردونه شانس" is copied to your clipboard before running!
# Note: make sure the language of your system is set to ENGLSIH, not persian
# --------------------------

print("Starting in 1 second. Switch to Telegram Desktop and do not touch your mouse!")
print("FAILSAFE IS ON: Slam your mouse into any corner of the screen to panic-stop.")
time.sleep(1)

# Grabs the exact time you start the script
base_time = datetime.now()
# manually set a starting time
base_time = datetime(2025, 10, 15, 20, 00)
# --- NEW: PRE-CALCULATE AND PRINT ALL TIMES ---
# print("\n=== UPCOMING SCHEDULE FOR THE NEXT 60 DAYS ===")
# for day in range(1, total_messages + 1):
#     preview_time = base_time + timedelta(minutes=3 * day)
#     print(f"Day {day}: {preview_time.strftime('%H:%M')}")
# print("==============================================\n")
# ----------------------------------------------


for day in range(1, total_messages + 1):
    # 1. Paste the command 
    pyautogui.hotkey('ctrl', 'v') 
    time.sleep(0.2)

    # 2. Right-click the send button
#     pya049    utogui.moveTo(send_button_x, send_button_y)
#     pyautogui.click(button='left')
    pyautogui.press('enter')
    time.sleep(0.3)

    # Calculate the new time (shifting the clock forward by 3 mins per loop)
    run_time = base_time + timedelta(minutes=3 * day)
    time_string = run_time.strftime('%H%M')

    # 4. Click the time input box and type the calculated time
    pyautogui.press('backspace', presses=4, interval=0.05) # Clear old time just in case
    print(f'writing time: {time_string}')
    
#     pyautogui.write(time_string)
    pyautogui.write(time_string[0])
    time.sleep(0.02)
    pyautogui.write(time_string[1])
    time.sleep(0.02)
    pyautogui.write(time_string[2])
    time.sleep(0.02)
    pyautogui.write(time_string[3])
#     time.sleep(0.05)

    # --- MANUAL DATE SELECTION ---
    print(f"[{day}/{total_messages}] Please manually click the day on the calendar now...")
    pyautogui.press('tab')
    # after 29 days, press a key down
    if day >= 29:
        pyautogui.press('down')
    if day >= 57:
        pyautogui.press('down')
#     pyautogui.press('down')
    
    time.sleep(1.0) # Gives you 1 second to click the correct date. Change this if you need more/less time!
    # -----------------------------
    
    # 5. Click the final "Schedule" button
    pyautogui.press('enter')
    
    
    print(f"Scheduled message with time: {time_string}")
    time.sleep(0.15) # Brief pause before the next loop starts