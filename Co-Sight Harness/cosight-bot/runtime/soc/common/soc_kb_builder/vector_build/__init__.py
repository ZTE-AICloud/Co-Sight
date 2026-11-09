#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOC KB 向量库构建核心包（自 scripts/sync_soc_rag/ 迁入，反向依赖治理）。

模块：
  - build_soc_vector.py    全量构建入口（python -m common.soc_kb_builder.vector_build.build_soc_vector）
  - common_processor.py    普通文档（01_Specs_PD）单文件事件处理
  - historical_processor.py 历史应答（02_Historical_Responses）处理
  - product_taxonomy.py    产品分类树生成
  - node_sections.py       文件节点 → 章节标题清单
  - soc_rag_helpers.py     指纹算式 / .md 命名规则等共用 helper

依赖方向约定：本包只允许依赖 runtime 内部模块（common.* / watch_dog.*），
不得反向依赖 scripts/sync_soc_rag/。
"""
