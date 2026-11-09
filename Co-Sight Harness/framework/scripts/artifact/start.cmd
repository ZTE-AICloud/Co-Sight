@echo off
rem Co-Sight Harness launcher (Windows)
rem
rem   start.cmd                  default 127.0.0.1:4300, data dir %USERPROFILE%\.cosight-harness
rem   start.cmd --port 8080      same options as: node start.mjs
rem   start.cmd --help
rem
rem The config file is "cosight.env" next to this file (plain KEY=VALUE text, see
rem cosight.env.example). It is parsed by start.mjs, not by this script.
rem
rem Keep this file ASCII-only - see the note in install.cmd. Chinese documentation
rem (including what to try when startup fails) lives in README.md.
rem
rem Stop the server with Ctrl-C in this window.

setlocal
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

node start.mjs %*
set "CODE=%ERRORLEVEL%"

rem A double-clicked window would otherwise vanish before the error can be read.
if not "%CODE%"=="0" pause

endlocal & exit /b %CODE%
