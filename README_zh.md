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
2.浏览器的模型配置需要到browser_simulation.py中修改web_model和planning_model信息
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
运行easy_manus_evals.py
若要修改使用到的大模型，修改llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision的值即可
```bash
if __name__ == '__main__':
    os.makedirs(WORKSPACE_PATH, exist_ok=True)
    os.makedirs(LOG_PATH, exist_ok=True)
    os.environ['WORKSPACE_PATH'] = WORKSPACE_PATH.as_posix()
    os.environ['RESULTS_PATH'] = WORKSPACE_PATH.as_posix()
    # https://huggingface.co/spaces/gaia-benchmark/leaderboard
    manus = easy_manus()
    results = gaia_level1(process_message=manus, task_id=[
        '384d0dd8-e8a4-4cfe-963c-d37f256e7662'],postcall=save_results )

    datestr = datetime.datetime.today().strftime('%Y%m%d%H%M%S')
    save_results(results, (WORKSPACE_PATH / f'result_level1_{datestr}.json').as_posix())
```

