@echo off
rem Co-Sight Harness uninstaller (Windows)
rem
rem Usage:
rem   uninstall.cmd                      remove the four plugins from Claude Code
rem   uninstall.cmd --dry-run            print what would happen, change nothing
rem   uninstall.cmd --purge-data --yes   also delete the data directory (sessions,
rem                                      workspaces and credentials are lost)
rem
rem Keep this file ASCII-only. cmd.exe reads it byte by byte as ANSI, so a UTF-8
rem Chinese comment becomes mojibake on a GBK console, and "chcp 65001" does not
rem help (the parser has already read the line). All Chinese documentation lives
rem in README.md instead.
rem
rem This file is intentionally tiny: node performs the real work in
rem "start.mjs --uninstall" (uninstall the plugins, drop the marketplaces our
rem installer copied into %USERPROFILE%\.claude, then optionally delete the data
rem directory). Keeping that logic in one place is the whole point - a second
rem copy here would drift from the POSIX one in uninstall.sh.
rem
rem Deleting the extracted folder is NOT enough on its own: the installer writes
rem four marketplaces plus four plugin registrations into Claude Code, and none
rem of that lives under this directory.
rem
rem Deliberately NOT done: no admin elevation, no system directory, no PATH edit,
rem no network access. The data directory is kept unless --purge-data is given.

setlocal
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

where node >nul 2>&1
if errorlevel 1 goto :no_node

rem The closing guidance (delete this extracted folder / the data directory is kept
rem unless --purge-data --yes / nothing changed under --dry-run) is printed by
rem start.mjs: only it knows whether we are inside an artifact or a source
rem checkout, and whether this run is a dry run. A second copy here would drift.
node start.mjs --uninstall %*

rem Save the exit code before "pause": pause is documented to clear ERRORLEVEL,
rem so the test below has to look at a saved copy, not at errorlevel itself.
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" goto :failed

rem Keep the window open when the script is double-clicked.
pause
exit /b 0

:no_node
echo.
echo Node.js was not found on PATH.
echo.
echo The uninstall logic lives in start.mjs and needs Node.js 22.19.0 or newer.
echo It uses built-in Node capabilities only - no npm, no pnpm, no network access.
echo If Node is installed but not on PATH, add its folder to PATH or call it
echo directly, for example: C:\nodejs\node.exe start.mjs --uninstall
echo.
pause
exit /b 1

:failed
echo.
echo Uninstall did not finish - see the message above.
echo (A plugin command failed, or --purge-data was given without --yes.)
echo.
pause
exit /b 1
