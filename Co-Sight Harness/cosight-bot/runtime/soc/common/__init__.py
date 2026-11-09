#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CoSightBot 公共模块（runtime/common）。

包含 index_api（索引状态/文件信息）、soc_vector_paths、port_resolver（状态根唯一来源）、
cosight_runtime（LLM 配置纯环境变量解析）等跨功能公共工具。

调用方（技能脚本）统一走 common.bootstrap 完成 sys.path 注入与 preflight，
不要手工拼 sys.path。
"""
