@echo off

set registry="--registry=https://artsh.zte.com.cn/artifactory/api/npm/rnia-npm-virtual/"
set scriptDir=%~dp0
cd ..
del /f package-lock.json
rmdir /s /q .angular

echo 开始安装仓库依赖...
cmd /c npm install --unsafe-perm --force --ignore-scripts %registry%
if %errorlevel% NEQ 0 (
    echo "==> 错误: 无法安装仓库依赖..."
    exit /b 1
)

echo 开始更新icon-font...
cmd /c npm update --force --ignore-scripts %registry% @rdkmaster/icon-font
if %errorlevel% NEQ 0 (
    echo "==> 错误: 图标库更新失败..."
    exit /b 1
)


echo 开始更新lui-sdk...
cmd /c npm update --force --ignore-scripts %registry% @rdkmaster/lui-sdk @rdkmaster/lui-sdk-mobile
if %errorlevel% NEQ 0 (
    echo "==> 错误: lui-sdk更新失败..."
    exit /b 1
)

echo 开始安装jigsaw和formly...
cmd /c npm install @rdkmaster/jigsaw@governance18 @rdkmaster/formly@governance18 --force --ignore-scripts %registry%
if %errorlevel% NEQ 0 (
    echo "==> 错误: 更新jigsaw到governance18版本失败..."
    exit /b 1
)

if not "%1" == "silent" pause


