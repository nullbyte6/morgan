@echo off
schtasks -Run /TN "ARLO_WAKE"
exit /b %errorlevel%
