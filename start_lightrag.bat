@echo off
REM ==========================================
REM  启动 LightRAG 服务 (读取 Co-Sight 环境变量配置)
REM ==========================================
REM  用法: 在 Co-Sight 目录下运行此脚本
REM        start_lightrag.bat
REM ==========================================

echo ===== 配置 LightRAG 环境变量 =====

REM LLM 配置（用于知识图谱构建时的实体抽取）
set LLM_BINDING=openai
set LLM_BINDING_HOST=https://coding.dashscope.aliyuncs.com/v1
set LLM_BINDING_API_KEY=your_api_key_here
set LLM_MODEL=glm-5

REM Embedding 配置（核心！文档向量化）
set EMBEDDING_BINDING=openai
set EMBEDDING_BINDING_HOST=https://api.siliconflow.cn/v1
set EMBEDDING_BINDING_API_KEY=your_embedding_api_key_here
set EMBEDDING_MODEL=Qwen/Qwen3-Embedding-4B
set EMBEDDING_MAX_TOKEN_SIZE=8192

echo    LLM: %LLM_MODEL% via %LLM_BINDING%
echo    Embedding: %EMBEDDING_MODEL% via %EMBEDDING_BINDING% (Dim: 2560)
echo ===================================

echo.
echo 正在启动 LightRAG 服务...
lightrag-server --port 9621 --llm-binding openai --embedding-binding openai --embedding-dim 2560
