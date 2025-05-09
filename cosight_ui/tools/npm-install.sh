#!/bin/bash

# 切换到脚本所在目录
cd "$(dirname "$0")"
cd ..
rm -f package-lock.json
rm -rf .angular

echo "开始安装仓库依赖..."
if ! npm install --unsafe-perm --force --ignore-scripts ${registry}; then
    echo "==> 错误: 无法安装仓库依赖..."
    exit 1
fi

echo "开始更新icon-font..."
if ! npm update --force ${registry} @rdkmaster/icon-font; then
    echo "==> 错误: 图标更新失败..."
    exit 1
fi

echo "开始更新lui-sdk..."
npm install @rdkmaster/lui-sdk --force $registry
if [ "$?" != "0" ]; then
    echo "==> 错误: 更新lui-sdk失败..."
    exit 1
fi

echo "开始安装jigsaw和formly..."
if ! npm install @rdkmaster/jigsaw@governance18 @rdkmaster/formly@governance18 --force ${registry}; then
    echo "==> 错误: 安装jigsaw的governance18版本失败..."
    exit 1
fi
