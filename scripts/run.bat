@echo off
schtasks -Run /TN "MORGAN_WAKE"
exit /b %errorlevel%
