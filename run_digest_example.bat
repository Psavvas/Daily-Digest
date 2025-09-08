
@echo off
REM Example wrapper to run your digest via Task Scheduler.
REM EDIT the paths below before use.

set DIGEST_DIR=C:\Path\To\DailyDigest
set PYTHON_EXE=C:\Users\YOURNAME\AppData\Local\Programs\Python\Python311\python.exe

cd /d "%DIGEST_DIR%"
"%PYTHON_EXE%" daily_digest.py >> digest.log 2>&1
