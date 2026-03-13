# Copyright 2025 ZTE Corporation. All Rights Reserved.
# Licensed under the Apache License, Version 2.0

import os

from app.common.logger_util import logger


def _create_llm_for_agent(agent_config: dict, fallback_llm=None):
    provider_id = agent_config.get("provider_id", "")
    model_name = agent_config.get("model_name", "")
    thinking_mode = agent_config.get("thinking_mode")

    if not provider_id or not model_name:
        if fallback_llm is not None and isinstance(thinking_mode, bool):
            try:
                from app.cosight.llm.chat_llm import ChatLLM

                return ChatLLM(
                    base_url=fallback_llm.base_url,
                    api_key=fallback_llm.api_key,
                    model=fallback_llm.model,
                    client=fallback_llm.client,
                    max_tokens=fallback_llm.max_tokens,
                    temperature=fallback_llm.temperature,
                    stream=fallback_llm.stream,
                    tools=list(getattr(fallback_llm, "tools", []) or []),
                    thinking_mode=thinking_mode,
                )
            except Exception as exc:
                logger.warning("Failed to clone fallback LLM for thinking_mode override: %s", exc)
        return fallback_llm

    try:
        from cosight_server.deep_research.routers.settings import _read_providers
        from llm import set_model

        providers = _read_providers()
        provider = next((item for item in providers if item.get("id") == provider_id), None)
        if not provider:
            logger.warning("Provider '%s' not found, using fallback LLM", provider_id)
            return fallback_llm

        model_config = {
            "base_url": provider.get("base_url", ""),
            "api_key": provider.get("api_key", ""),
            "model": model_name,
            "proxy": provider.get("proxy", ""),
            "max_tokens": None,
            "temperature": None,
            "thinking_mode": thinking_mode if isinstance(thinking_mode, bool) else None,
        }
        custom_llm = set_model(model_config)
        logger.info(
            "Created custom LLM for agent: provider=%s, model=%s, thinking_mode=%s",
            provider_id,
            model_name,
            model_config["thinking_mode"],
        )
        return custom_llm
    except Exception as exc:
        logger.warning(
            "Failed to create custom LLM for agent (provider=%s, model=%s): %s",
            provider_id,
            model_name,
            exc,
        )
        return fallback_llm


def _append_custom_system_prompt(agent, custom_prompt: str | None, header: str):
    if not custom_prompt:
        return
    custom_prompt = custom_prompt.strip()
    if not custom_prompt:
        return

    if agent.history and agent.history[0].get("role") == "system":
        base_prompt = agent.history[0].get("content", "")
        agent.history[0]["content"] = f"{base_prompt}\n\n{header}\n{custom_prompt}"
    else:
        agent.history.insert(0, {"role": "system", "content": custom_prompt})


def create_planner_runtime(agent_config: dict, fallback_llm, plan_id: str):
    from app.agent_dispatcher.infrastructure.entity.AgentInstance import AgentInstance
    from app.agent_dispatcher.infrastructure.entity.AgentTemplate import AgentTemplate
    from app.cosight.agent.planner.task_plannr_agent import TaskPlannerAgent
    from app.cosight.agent.runtime.skill_catalog import build_planner_skills

    planner_llm = _create_llm_for_agent(agent_config, fallback_llm)

    template = AgentTemplate(
        template_name=f"planner_template_{agent_config.get('id', 'default')}",
        template_version="v1",
        agent_type="planner_agent",
        display_name_zh=agent_config.get("name", "任务规划专家"),
        display_name_en="Task Planning Expert",
        description_zh=agent_config.get("description", "负责任务分解和规划"),
        description_en="Responsible for task decomposition and planning",
        service_name="planning_service",
        service_version="v1",
        default_replay_zh=agent_config.get("name", "任务规划专家"),
        default_replay_en="Task Planning Expert",
        skills=build_planner_skills(),
    )

    instance = AgentInstance(
        instance_id=f"planner_{agent_config.get('id', 'default')}_{plan_id}",
        instance_name=f"Planner {agent_config.get('name', 'default')}",
        template_name=template.template_name,
        template_version="v1",
        display_name_zh=agent_config.get("name", "任务规划专家"),
        display_name_en="Task Planning Expert",
        description_zh=agent_config.get("description", ""),
        description_en="",
        service_name="planning_service",
        service_version="v1",
        template=template,
    )

    planner = TaskPlannerAgent(instance, planner_llm, plan_id)
    custom_prompt = agent_config.get("system_prompt", "").strip()
    return planner, custom_prompt if custom_prompt else None


def create_actor_runtime(
    agent_config: dict,
    fallback_act_llm,
    fallback_vision_llm,
    fallback_tool_llm,
    plan_id: str,
    work_space_path: str,
    step_index: int = 0,
):
    from app.agent_dispatcher.infrastructure.entity.AgentInstance import AgentInstance
    from app.agent_dispatcher.infrastructure.entity.AgentTemplate import AgentTemplate
    from app.cosight.agent.actor.instance.actor_agent_instance import create_actor_instance
    from app.cosight.agent.actor.task_actor_agent import TaskActorAgent
    from app.cosight.agent.runtime.skill_catalog import build_actor_skills, validate_skill_names

    actor_llm = _create_llm_for_agent(agent_config, fallback_act_llm)
    skill_names = agent_config.get("skills", [])

    if skill_names:
        invalid_skills = validate_skill_names(skill_names)
        if invalid_skills:
            raise ValueError(f"Invalid actor skills: {invalid_skills}")

    if not skill_names:
        logger.info(
            "Agent '%s' has no skill restrictions, using default actor toolset",
            agent_config.get("name"),
        )
        instance = create_actor_instance(f"actor_for_step_{step_index}", work_space_path)
        actor = TaskActorAgent(
            instance,
            actor_llm,
            fallback_vision_llm,
            fallback_tool_llm,
            plan_id,
            work_space_path=work_space_path,
        )
    else:
        skills = build_actor_skills(skill_names, work_space_path)
        if "mark_step" not in skill_names:
            from app.cosight.agent.actor.instance.actor_agent_skill import mark_step_skill

            skills.append(mark_step_skill())

        template = AgentTemplate(
            template_name=f"actor_template_{agent_config.get('id', 'custom')}",
            template_version="v1",
            agent_type="actor_agent",
            display_name_zh=agent_config.get("name", "任务执行专家"),
            display_name_en="Task Actor",
            description_zh=agent_config.get("description", ""),
            description_en="",
            service_name="execution_service",
            service_version="v1",
            default_replay_zh=agent_config.get("name", "任务执行专家"),
            default_replay_en="Task Actor",
            skills=skills,
        )

        instance = AgentInstance(
            instance_id=f"actor_{agent_config.get('id', 'custom')}_step_{step_index}",
            instance_name=f"Actor {agent_config.get('name', 'custom')}",
            template_name=template.template_name,
            template_version="v1",
            display_name_zh=agent_config.get("name", "任务执行专家"),
            display_name_en="Task Actor",
            description_zh=agent_config.get("description", ""),
            description_en="",
            service_name="execution_service",
            service_version="v1",
            template=template,
        )

        actor = TaskActorAgent(
            instance,
            actor_llm,
            fallback_vision_llm,
            fallback_tool_llm,
            plan_id,
            work_space_path=work_space_path,
        )

    _append_custom_system_prompt(
        actor,
        agent_config.get("system_prompt", "").strip(),
        "# Additional Actor Instructions",
    )
    return actor
