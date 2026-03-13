import os
import uuid
import json
from pathlib import Path
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.common.logger_util import logger
from cosight_server.deep_research.full_agent.agent import FullAgent
from cosight_server.deep_research.llm import set_model
from config.config import get_act_model_config  # 复用 act 模型配置

router = APIRouter(prefix="/full_agent")

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    # 为每个连接创建独立的工作目录
    session_id = str(uuid.uuid4())[:8]
    work_dir = Path("work_space") / "full_agent" / session_id
    work_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"FullAgent session {session_id} started at {work_dir}")

    # 获取模型配置（可单独配置 FULL_AGENT 模型，否则复用 act 模型）
    model_config = get_act_model_config()  # 或者从环境变量读取 FULL_AGENT_*
    
    agent = FullAgent(work_dir, model_config)

    try:
        while True:
            data = await websocket.receive_text()
            # 处理用户消息
            response = agent.process_message(data)
            await websocket.send_text(json.dumps({"type": "response", "content": response}))
    except WebSocketDisconnect:
        logger.info(f"FullAgent session {session_id} disconnected")
        # 可清理工作目录等
    except Exception as e:
        logger.error(f"FullAgent session {session_id} error: {e}", exc_info=True)
        await websocket.close()