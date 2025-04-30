## 安装指南


### 方式一：使用 conda

1. 创建新的 conda 环境：

```bash
conda create -n Co-Sight python=3.11
conda activate Co-Sight
```

2. 克隆仓库：

```bash
git clone 
cd 
```

3. 安装依赖：

```bash
pip install -r requirements.txt
```

## 配置说明

Co-Sight 需要配置使用的 LLM API，请按以下步骤设置：

1. 打开 `.env`文件，并编辑以下内容，添加 API 密钥和自定义设置：

```plaintext
# 全局 LLM 配置
API_KEY=your-key-here
API_BASE_URL=your-base-url-here
MODEL_NAME=your-model-here
MAX_TOKENS=4096
TEMPERATURE=0.0
PROXY=

# 可选特定 LLM 模型配置
# Co-Sight可分层配置模型：规划，执行，工具以及多模态
# 在对应的模型配置项下面，配置模型参数（API_KEY，API_BASE_URL，MODEL_NAME都配置方可生效）

# # ===== PLAN MODEL =====
# TOOL_API_KEY=
# TOOL_API_BASE_URL=
# TOOL_MODEL_NAME=
# TOOL_MAX_TOKENS=
# TOOL_TEMPERATURE=
# TOOL_PROXY=

# # ===== ACT MODEL =====

# # ===== TOOL MODEL =====

# # ===== VISION MODEL =====


# 搜索工具配置
# ===== 工具API =====

# tavily搜索引擎
TAVILY_API_KEY=tvly-your-key-here

# google搜索引擎
GOOGLE_API_KEY=your-key-here
SEARCH_ENGINE_ID=your-id-here
```
## 模型API-KEY获取  
大模型（到对应网站购买api）
```
deepseek:   https://api-docs.deepseek.com/zh-cn/
qwen:       https://bailian.console.aliyun.com/?tab=api#/api
...
```
工具大模型
```
Tavily搜索引擎的API_KEY（可去官网申请，每月每账号1000次免费访问）
https://app.tavily.com/home

google_search搜索引擎的API_KEY（可去官网申请，每天可免费访问100次）
进入  https://developers.google.com/custom-search/v1/overview?hl=zh-cn
点击 overview 中的 Get a Key，需要登录谷歌帐号，以及注册谷歌云帐号并且创建一个 project，得到一个 Key(GOOGLE_API_KEY)。
进入  https://programmablesearchengine.google.com/controlpanel/all   获取SEARCH_ENGINE_ID
```

## 快速启动

### 直接运行 Co-Sight：
```bash
运行CoSight.py
if __name__ == '__main__':
    # 配置工作区
    os.makedirs(WORKSPACE_PATH, exist_ok=True)
    os.environ['WORKSPACE_PATH'] = WORKSPACE_PATH

    # 配置CoSight
    cosight = CoSight(llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision)

    # 运行CoSight
    result = cosight.execute("帮我写一篇中兴通讯的分析报告")
    print(f"final result is {result}")
```

### 前后端运行：  

#### 前端配置：

linux：
```bash
cd cosight_ui/tools
sh npm-install.sh
```

windows：
```bash
cd cosight_ui/tools
运行 npm-install.bat
```

前端启动：
```bash
cd cosight_ui
执行 npm start

浏览器访问: https://localhost:4200/
```

#### 后端启动
```bash
cd cosight_server/deep_research

运行 main.py

if __name__ == '__main__':
    import argparse
    import uvicorn
    
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description=i18n.t('ai_search_plugin_description'))
    parser.add_argument('-p', '--port', type=int, help=i18n.t('ai_search_port_help'), default=None)
    args = parser.parse_args()
    
    logger.info('*****************')
    logger.info('plugin server staring...')
    args.port = custom_config.get("search_port")

    uvicorn.run(app=app, host="0.0.0.0", port=int(args.port))
```

生成文件可在`cosight_server/work_space`文件夹中查看