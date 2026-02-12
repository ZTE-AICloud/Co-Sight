"""
Root-level actor package for business-specific execution agents.

现有内置执行器：
- actor.netopt_actor: 网优资料整理执行器（网优资料整理与报告）

新增自定义业务 Actor 的推荐目录结构：
- actor/<your_actor_id>/agent.py       # 具体执行器类（继承 BaseAgent）
- actor/<your_actor_id>/instance.py    # create_xxx_template / create_xxx_instance
- actor/<your_actor_id>/prompt.py      # 系统 prompt、执行 prompt
- actor/<your_actor_id>/tools.py       # 该执行器专属的工具函数集合

接入新 Actor 的步骤（简要）：
1. 在上面的目录结构下实现你的业务逻辑；
2. 在 app/cosight/agent/actor/registry.py 中注册新的 Actor 类（agent_id、描述等）；
3. 在 app/cosight/agent/actor/__init__.py 中按需要导出新的 Actor；
4. 如需打包到可执行文件，记得在 tools/Cosight.spec 的 hiddenimports 中加入对应的模块路径。
"""


