@echo off
REM ============================================================
REM  AI Chat launcher
REM  Prefers a Python runtime bundled next to this file (runtime\python),
REM  then falls back to a system Python with tkinter.
REM  NOTE: keep this file ASCII-only - cmd.exe parses .bat in the OEM
REM  codepage, so UTF-8 text would break the syntax.
REM ============================================================
setlocal
set "APPDIR=%~dp0"
set "PY="

if exist "%APPDIR%runtime\python\pythonw.exe" set "PY=%APPDIR%runtime\python\pythonw.exe"
if not defined PY if exist "%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe" (
  set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe"
)

if not defined PY (
  for %%P in (pythonw.exe) do if not defined PY if not "%%~$PATH:P"=="" set "PY=%%~$PATH:P"
)
if not defined PY (
  for %%P in (python.exe) do if not defined PY if not "%%~$PATH:P"=="" set "PY=%%~$PATH:P"
)

if not defined PY (
  echo [ERROR] Python not found. Install Python 3.10+ with tkinter, or put a
  echo         runtime\python folder next to this file.
  pause
  exit /b 1
)

start "" "%PY%" "%APPDIR%AIChat.pyw"
endlocal
