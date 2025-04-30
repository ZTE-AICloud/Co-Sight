@echo off

echo --------------------------------
echo compiling...
cmd /c npm run build

if not "%1" == "silent" pause
