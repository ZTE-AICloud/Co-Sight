@echo off
rem Co-Sight Harness installer (Windows)
rem
rem Usage:
rem   install.cmd                 use the default data directory (%USERPROFILE%\.cosight-harness)
rem   install.cmd --home D:\ch    use a specific data directory
rem
rem Keep this file ASCII-only. cmd.exe reads it byte by byte as ANSI, so a UTF-8
rem Chinese comment becomes mojibake on a GBK console, and "chcp 65001" does not
rem help (the parser has already read the line). All Chinese documentation lives in
rem README.md instead.
rem
rem This file is intentionally tiny: node performs the real work in
rem "start.mjs --install" (Node version check, data directory, config file,
rem and installing the four Claude Code plugins).
rem Keeping that logic in one place is the whole point - a second copy here would
rem drift from the POSIX one in install.sh.
rem
rem Deliberately NOT done: no admin elevation, no system directory, no PATH edit,
rem no network access, no background service.

setlocal
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

where node >nul 2>&1
if errorlevel 1 goto :no_node

node start.mjs --install %*
if errorlevel 1 goto :failed

echo.
echo Next step: run start.cmd   or: node start.mjs
echo Run start.cmd --help for all options.
echo.
pause
exit /b 0

:no_node
echo.
echo Node.js was not found on PATH.
echo.
echo This program requires Node.js 22.19.0 or newer. The 24.x line also works.
echo It uses built-in Node capabilities only - no npm, no pnpm, no network access.
echo Download: https://nodejs.org/en/download
echo.
echo If Node is installed but not on PATH, add its folder to PATH or call it
echo directly, for example: C:\nodejs\node.exe start.mjs --install
echo.
pause
exit /b 1

:failed
echo.
echo Install failed - see the message above.
echo.
pause
exit /b 1
