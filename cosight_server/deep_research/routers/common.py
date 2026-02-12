# Copyright 2025 ZTE Corporation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
import json
import shutil
import tempfile
import zipfile

from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.params import Body

from cosight_server.sdk.common.api_result import json_result
from cosight_server.sdk.common.cache import Cache
from app.common.logger_util import logger

commonRouter = APIRouter()

server_start_timestamp = int(datetime.now().timestamp() * 1000)

@commonRouter.get("/deep-research/server-timestamp")
async def get_server_timestamp():
    """获取服务器启动时间戳"""
    return json_result(0, 'success', {
        'timestamp': server_start_timestamp
    })

@commonRouter.post("/deep-research/stop-message")
async def stop_message(body: Dict = Body(...)):
    messageId = body.get("messageId")
    logger.info(f"stop_message >>>>>>>>>> is called, messageId: {messageId}")
    Cache.put(f"is_message_stopped_{messageId}", True)
    return json_result(0, 'success', {
        'status': 'stopped'
    })


def _parse_skill_front_matter(skill_md_path: Path) -> Optional[dict]:
    """
    解析 SKILL.md 顶部的 YAML front matter，提取 name/description。
    期望格式：
    ---
    name: xxx
    description: yyy
    ---
    """
    try:
        text = skill_md_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.warning(f"读取SKILL.md失败: {skill_md_path}, err={e}")
        return None

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    # 找到第二个 ---
    end_idx = None
    for i in range(1, min(len(lines), 200)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None

    meta: dict = {}
    for raw in lines[1:end_idx]:
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if ":" not in s:
            continue
        k, v = s.split(":", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            meta[k] = v

    name = meta.get("name")
    description = meta.get("description")
    if not name:
        # 兜底：用目录名作为 name
        name = skill_md_path.parent.name
    if description is None:
        description = ""

    return {"name": name, "description": description}


@commonRouter.get("/deep-research/skills")
async def list_skills():
    """
    返回 skills 目录下的技能清单（只返回 name/description）。
    注意：为了避免与静态挂载 {base_api_url}/skills 冲突，这里使用 /deep-research/skills。
    """
    repo_root = Path(__file__).resolve().parents[3]  # .../Co-Sight
    skills_dir = repo_root / "skills"
    skills: List[dict] = []

    try:
        if skills_dir.exists() and skills_dir.is_dir():
            for child in skills_dir.iterdir():
                if not child.is_dir():
                    continue
                skill_md = child / "SKILL.md"
                if not skill_md.exists():
                    continue
                parsed = _parse_skill_front_matter(skill_md)
                if parsed:
                    skills.append(parsed)
    except Exception as e:
        logger.error(f"扫描skills目录失败: {skills_dir}, err={e}", exc_info=True)

    skills = sorted(skills, key=lambda x: (x.get("name") or "").lower())
    return json_result(0, "success", {"count": len(skills), "skills": skills})


def _load_agent_card(card_path: Path) -> Optional[dict]:
    """
    解析 actor/*/agent_card.json，提取 agent_id、agent_name、agent_description、agent_icon、skills。
    期望格式：{"agent_id": "xxx", "agent_name": "xxx", "agent_description": "xxx",
              "agent_icon": "xxx", "skills": ["skill1", "skill2"]}
    """
    try:
        text = card_path.read_text(encoding="utf-8", errors="ignore")
        data = json.loads(text)
    except Exception as e:
        logger.warning(f"解析 agent_card.json 失败: {card_path}, err={e}")
        return None

    agent_id = data.get("agent_id")
    if not agent_id:
        return None

    return {
        "agent_id": str(agent_id),
        "agent_name": data.get("agent_name") or "",
        "agent_description": data.get("agent_description") or "",
        "agent_icon": data.get("agent_icon") or "",
        "skills": data.get("skills") if isinstance(data.get("skills"), list) else [],
    }


@commonRouter.get("/deep-research/agents")
async def list_agents():
    """
    返回智能体清单。扫描规则：
    - actor/（仓库根目录）：扫描所有子目录的 agent_card.json（用于自定义业务 Actor）
    - app/cosight/agent/actor/：仅读取 openclaw、task_actor 两个文件夹的 agent_card.json
    """
    repo_root = Path(__file__).resolve().parents[3]  # .../Co-Sight
    agents_by_id: Dict[str, dict] = {}

    try:
        # actor/：扫描所有子目录
        actor_dir = repo_root / "actor"
        if actor_dir.exists() and actor_dir.is_dir():
            for child in actor_dir.iterdir():
                if not child.is_dir():
                    continue
                card_path = child / "agent_card.json"
                if not card_path.exists():
                    continue
                parsed = _load_agent_card(card_path)
                if parsed:
                    aid = parsed.get("agent_id") or ""
                    if aid:
                        agents_by_id[aid] = parsed

        # app/cosight/agent/actor/：仅读取 openclaw、task_actor 两个文件夹
        app_actor_dir = repo_root / "app" / "cosight" / "agent" / "actor"
        if app_actor_dir.exists() and app_actor_dir.is_dir():
            for folder_name in ("openclaw", "task_actor"):
                child = app_actor_dir / folder_name
                if not child.is_dir():
                    continue
                card_path = child / "agent_card.json"
                if not card_path.exists():
                    continue
                parsed = _load_agent_card(card_path)
                if parsed:
                    aid = parsed.get("agent_id") or ""
                    if aid:
                        agents_by_id[aid] = parsed
    except Exception as e:
        logger.error(f"扫描 agent 目录失败: {e}", exc_info=True)

    agents = sorted(agents_by_id.values(), key=lambda x: (x.get("agent_id") or "").lower())
    return json_result(0, "success", {"count": len(agents), "agents": agents})


@commonRouter.post("/deep-research/skills/import")
async def import_skill_zip(
    file: UploadFile = File(...),
    overwrite: bool = Query(False, description="Whether to overwrite existing skill folder")
):
    """
    导入 skill 压缩包（仅支持 .zip）。
    规则：
    - 只接受 zip
    - zip 第一层必须是单个目录（skill 目录）
    - 该目录下必须包含 SKILL.md，否则拒绝导入
    - 默认不覆盖已有同名目录（overwrite=false）
    """
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip is supported")

    repo_root = Path(__file__).resolve().parents[3]  # .../Co-Sight
    skills_dir = repo_root / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="cosight_skill_import_") as tmp:
        tmp_dir = Path(tmp)
        zip_path = tmp_dir / "upload.zip"

        # 保存上传文件
        try:
            content = await file.read()
            zip_path.write_bytes(content)
        except Exception as e:
            logger.error(f"保存上传zip失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to read upload")

        extract_dir = tmp_dir / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)

        # 解压并做安全校验
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                # ZipSlip 检查 + 解压
                dest_root = extract_dir.resolve()
                for member in zf.infolist():
                    name = member.filename
                    if not name:
                        continue
                    if name.startswith("__MACOSX/"):
                        continue
                    # 目录项跳过，文件项校验路径
                    target = (dest_root / name).resolve()
                    if target != dest_root and dest_root not in target.parents:
                        raise HTTPException(status_code=400, detail=f"Illegal path in zip: {name}")
                zf.extractall(extract_dir)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"解压zip失败: {e}", exc_info=True)
            raise HTTPException(status_code=400, detail="Invalid zip file")

        # 找 zip 第一层目录
        top_levels: set[str] = set()
        for p in extract_dir.rglob("*"):
            rel = p.relative_to(extract_dir)
            if not rel.parts:
                continue
            # 忽略 __MACOSX
            if rel.parts[0] == "__MACOSX":
                continue
            top_levels.add(rel.parts[0])

        if len(top_levels) != 1:
            raise HTTPException(status_code=400, detail="Zip must contain exactly one top-level skill folder")

        skill_folder_name = next(iter(top_levels))
        extracted_skill_dir = extract_dir / skill_folder_name
        if not extracted_skill_dir.is_dir():
            raise HTTPException(status_code=400, detail="Top-level entry must be a folder")

        # 必须包含 SKILL.md
        if not (extracted_skill_dir / "SKILL.md").exists():
            raise HTTPException(status_code=400, detail=f"SKILL.md not found in top-level folder: {skill_folder_name}")

        dest_skill_dir = skills_dir / skill_folder_name
        if dest_skill_dir.exists():
            if not overwrite:
                raise HTTPException(status_code=409, detail=f"Skill folder already exists: {skill_folder_name}")
            shutil.rmtree(dest_skill_dir)

        try:
            shutil.move(str(extracted_skill_dir), str(dest_skill_dir))
        except Exception as e:
            logger.error(f"导入skill失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to import skill")

        return json_result(0, "success", {"imported": skill_folder_name})