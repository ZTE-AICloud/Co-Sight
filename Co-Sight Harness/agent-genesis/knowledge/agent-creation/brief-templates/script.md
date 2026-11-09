# Brief 工序模板 — script（确定性脚本）

> 红线（DF-M4）: 可独立运行，不依赖 LLM 上下文；LLM 只做生成与策略，裁决归脚本

## 生成工序（3 步）

1. **CLI 入口契约**: 参数表（含无副作用模式 --list/--help）+ 退出码语义（失败种类分明，禁静默吞错）
2. **沙箱/路径约束**: 写位置白名单（正则）、越界即拒——CD2 的脚本层落实（防事故 #3 类绕过）
3. **import/包根正确性**: PYTHONPATH/包根参数（防事故 #2 类假击杀）；超时与导入错误归类
   【自查】py_compile 通过? --list 可运行? 反模式清单（无 import-root / 沙箱正则可绕过）逐项排除

## 落点规则

skill 私有脚本→该 skill 的 `scripts/`；项目级脚本→根 `scripts/`（如 mutate.py/run_tests.py）。
**确定性内容禁止写进 SKILL.md 让 LLM 执行**（DF-M4）。

## 自样例

同 build 中首个 script 生成后，后续 script 与其保持同构；已读过可跳过。
