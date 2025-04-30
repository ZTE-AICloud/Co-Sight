# NAE-Manus 构建指南

本指南将帮助你完成 NAE-Manus 的构建过程，包括前端构建和可执行文件打包。

## 环境准备

### 1. Python 环境
确保你已经安装了 Python 3.8 或更高版本。

### 2. 安装 PyInstaller
```bash
# 安装最新版本的 PyInstaller
pip install pyinstaller

# 如果需要特定版本，例如：
pip install pyinstaller==6.13.0
```

### 3. Node.js 环境
前端构建需要 Node.js 环境：
1. 安装 Node.js (推荐 v16 或更高版本)
2. 进入前端项目目录并安装依赖：
```bash
cd cosight_ui
npm install
```

## 构建流程

### 1. 构建前端 (build_web.py)
这个脚本会构建前端代码并将其复制到正确的位置。

```bash
# 方法1：直接运行脚本
python tools/build_web.py

# 方法2：使用 VS Code 调试
# 1. 打开 VS Code
# 2. 按 F5 或点击调试按钮
# 3. 选择 "Python: Build Web" 配置
```

脚本会：
- 在 manus_ui 目录下执行 `npm run build`
- 清空 manus_server/web 目录
- 将构建后的文件复制到 manus_server/web 目录

### 2. 打包可执行文件 (build.py)
这个脚本会将整个应用打包成一个可执行文件。

```bash
# 方法1：直接运行脚本
python tools/build.py

# 方法2：使用 VS Code 调试
# 1. 打开 VS Code
# 2. 按 F5 或点击调试按钮
# 3. 选择 "Python: Build Executable" 配置
```

脚本会：
- 创建必要的 spec 文件
- 打包应用程序及其依赖
- 复制所需的静态文件和配置
- 创建启动脚本 (run.bat)

## 输出文件

构建完成后，你可以在以下位置找到输出文件： 