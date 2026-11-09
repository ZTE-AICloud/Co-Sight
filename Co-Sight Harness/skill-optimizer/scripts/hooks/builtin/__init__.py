"""
scripts/hooks/builtin — 内置通用 hook 集合
==========================================

本目录放置与具体业务解耦的内置 hook，按 HookTrigger 分文件组织。
任何 builtin hook 都应：
  1. 不假设任何具体业务路径（phase*/RAN-*/iMate 等）
  2. 失败时通过 return False 表达，由调用方决定是否中断主流程
  3. 落盘日志到 {SKILLX_CURRENT_TASK_DIR}/_debug/hooks.log

新加 builtin：在此目录新增 .py，定义模块级 HOOK_SPECS 列表，
registry.load_builtin_hooks() 会自动发现并注册。
"""
