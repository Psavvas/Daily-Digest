# 📨Daily-Digest
**DailyDigest** is a Python application that automatically generates and sends a daily summary email containing your upcoming calendar events, reminders, local weather, and a motivational quote. Designed for personal productivity, it integrates with iCalendar feeds, Apple Reminders, and the OpenWeatherMap API to deliver a clean, informative digest to your inbox each morning.
### ✨Features
* Calendar Integration: Fetches events from multiple iCalendar (.ics) URLs.
* Reminders: Loads tasks from a Apple Reminders through Apple Shortcuts and a customizable JSON file.
*	Weather Updates: Retrieves current weather conditions using OpenWeatherMap.
*	Motivational Quotes: Includes a daily quote from ZenQuotes or fallback options.
*	Customizable Time Zone & Range: Supports configurable time zones and days ahead.
*	HTML Email Output: Sends a well-formatted, mobile-friendly email summary.
# 💽Installation
### ❗Requirements
* iOS Device with Apple Shortcuts (for reminders syncing)
* Python
* Cloud Storage Service with automated syncing for both devices (was using iCloud)
### 📄Step-by-Step Guide
1. **Install and configure Apple Shortcut**
   * Duplicate Reminder to Digest Shortcut: [https://www.icloud.com/shortcuts/ccd398ae84c1422d8db230859b608c53](https://www.icloud.com/shortcuts/ccd398ae84c1422d8db230859b608c53)
   * Chose location where JSON file saves to (Shortcuts Folder for instance in iCloud Drive)
   * Setup Apple Automation to run Reminder Shortcut daily at ~0600
2. **Clone Repository and Install Dependecies**
   * Clone GitHub Repository
   * Install Dependecies: `pip install -r requirements.txt`
3. **Modify Code in `Config.json`**
   * Insert iCal link for each Calendar wanting to be synced to Daily Digest
   * Setup email information including sender and recipent information
   * Specify file location from dictionary created by Apple Shortcuts
# 🖥️Usage
* Run Script Manually using `python daily_digest.py`
* Setup Windows Task Scheduler to have program run daily at set time
