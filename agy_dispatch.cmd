@echo off
REM agy_dispatch.cmd — Windows wrapper that bypasses python.exe console flash.
REM
REM USE THIS instead of `python agy_dispatch.py ...` when invoking from bash/CMD.
REM
REM Reasoning: `python.exe` is a console-subsystem binary. Bash/CMD invocation
REM briefly flashes a conhost.exe window before agy_dispatch.py self-relaunches
REM under pythonw.exe. This wrapper jumps straight to pythonw.exe (GUI subsystem,
REM no console allocation), eliminating the parent flash.
REM
REM ConPTY/OpenConsole.exe child flash (from agy.exe spawn) is a Windows OS limit
REM and cannot be fully eliminated without Session 0 isolation (which breaks
REM UnityMCP connectivity). This wrapper minimizes flash to that single source.
REM
REM Usage from bash:
REM   cmd //c "F:\\Antigravity Projeler\\2d roguelite\\RIMA\\agy_dispatch.cmd" --task-file STAGING/foo.md --account laurethayday
REM
REM Or from PowerShell:
REM   & "F:\Antigravity Projeler\2d roguelite\RIMA\agy_dispatch.cmd" --task-file STAGING/foo.md
REM
REM IMPORTANT: this file MUST be saved with CRLF line endings (Windows batch
REM requirement). LF-only causes cmd to swallow the first char of each line
REM (REM -> EM, setlocal -> etlocal), breaking the wrapper silently.
REM
REM Output capture: pythonw inherits the parent's stdout/stderr handles, so
REM bash's run_in_background output redirection still works.

setlocal

REM Resolve pythonw.exe — FIRST match wins. Order matters: prefer the Python
REM install where pywinpty is installed (Python312 system as of 2026-05-26).
REM If pywinpty migrates to a different Python, reorder these lines.
set "PYTHONW="
if exist "C:\Program Files\Python312\pythonw.exe" set "PYTHONW=C:\Program Files\Python312\pythonw.exe" & goto :found
if exist "C:\Program Files\Python313\pythonw.exe" set "PYTHONW=C:\Program Files\Python313\pythonw.exe" & goto :found
if exist "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\pythonw.exe" set "PYTHONW=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\pythonw.exe" & goto :found
if exist "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python313\pythonw.exe" set "PYTHONW=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python313\pythonw.exe" & goto :found

echo ERROR: pythonw.exe not found in any known location. Falling back to python.exe (flash possible^).
set "PYTHONW=python"

:found
REM Mark as already-relaunched so agy_dispatch.py skips its own self-relaunch step.
set "AGY_DISPATCH_RELAUNCHED=1"

REM Launch pythonw with the agy_dispatch.py script in the same directory.
"%PYTHONW%" "%~dp0agy_dispatch.py" %*

endlocal
exit /b %ERRORLEVEL%
