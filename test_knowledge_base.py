"""
Co-Sight 知识库系统 (LightRAG) 单独测试脚本
============================================
全自动化测试：健康检查 → 创建知识库 → 插入文本 → 查询 → 清理

用法: python test_knowledge_base.py

前置条件:
  1. LightRAG 服务已启动: lightrag-server --port 9621
  2. Co-Sight 后端已启动: python cosight_server/deep_research/main.py
"""

import asyncio
import httpx
import json
import sys
import time

# === 配置 ===
COSIGHT_BASE = "http://localhost:7788/api/nae-deep-research/v1"
LIGHTRAG_DIRECT = "http://localhost:9621"

# 测试用的知识文本
TEST_KNOWLEDGE_TEXTS = [
    {
        "text": (
            "量子计算是一种利用量子力学原理进行计算的技术。"
            "量子比特（qubit）与经典比特不同，可以同时处于0和1的叠加态。"
            "量子纠缠是量子计算中的关键特性，两个纠缠的量子比特即使距离遥远也会瞬间关联。"
            "IBM、Google、微软等公司都在积极研发量子计算机。"
            "2019年，Google宣布实现了'量子霸权'，即量子计算机在特定任务上超越了最强的经典超级计算机。"
        ),
        "description": "量子计算基础知识"
    },
    {
        "text": (
            "人工智能(AI)的发展可以追溯到1956年达特茅斯会议。"
            "机器学习是AI的一个子领域，深度学习则是机器学习的一种方法。"
            "GPT（Generative Pre-trained Transformer）是OpenAI开发的大语言模型系列。"
            "2022年底发布的ChatGPT引爆了全球对AI的关注。"
            "大语言模型的训练需要海量的文本数据和庞大的计算资源。"
            "RAG（Retrieval-Augmented Generation）检索增强生成技术可以让大模型结合外部知识库回答问题。"
        ),
        "description": "人工智能发展简史"
    },
    {
        "text": (
            "LightRAG 是一个轻量级的检索增强生成框架，由香港大学团队开发。"
            "它支持四种查询模式：naive（朴素）、local（局部）、global（全局）、hybrid（混合）。"
            "LightRAG 内部会构建知识图谱，将文档中的实体和关系抽取并组织起来。"
            "相比传统的向量检索，LightRAG 的图谱检索可以更好地理解实体之间的关联。"
        ),
        "description": "LightRAG 框架介绍"
    }
]

TEST_QUERIES = [
    "什么是量子霸权？是哪家公司实现的？",
    "RAG技术是什么？和大语言模型有什么关系？",
    "LightRAG有哪些查询模式？",
]


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


async def test_health_check():
    """测试 1: 健康检查"""
    separator("测试 1: 健康检查")

    # 1a. 直接检查 LightRAG
    print("\n[1a] 直接检查 LightRAG 服务...")
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(f"{LIGHTRAG_DIRECT}/health")
            print(f"     LightRAG 直连: ✅ 状态码 {resp.status_code}")
            print(f"     返回: {resp.json()}")
        except Exception as e:
            print(f"     LightRAG 直连: ❌ 失败 - {e}")
            print(f"     ⚠️  请先启动 LightRAG: lightrag-server --port 9621")
            return False

    # 1b. 通过 Co-Sight 代理检查
    print("\n[1b] 通过 Co-Sight 代理检查 LightRAG...")
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(f"{COSIGHT_BASE}/deep-research/kb/health")
            data = resp.json()
            status = data.get("data", {}).get("status", "unknown")
            icon = "✅" if status == "connected" else "❌"
            print(f"     Co-Sight 代理: {icon} 状态 = {status}")
        except Exception as e:
            print(f"     Co-Sight 代理: ❌ 失败 - {e}")
            print(f"     ⚠️  请先启动 Co-Sight: python cosight_server/deep_research/main.py")
            return False

    return True


async def test_create_kb() -> str:
    """测试 2: 创建知识库"""
    separator("测试 2: 创建知识库")

    kb_name = f"自动测试KB_{int(time.time())}"
    print(f"\n   创建知识库: \"{kb_name}\"")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{COSIGHT_BASE}/deep-research/kb/create",
            json={"name": kb_name, "description": "由测试脚本自动创建，可随时删除"}
        )
        data = resp.json()

    if data.get("code") != 0:
        print(f"   ❌ 创建失败: {data.get('msg')}")
        return ""

    kb_id = data["data"]["id"]
    print(f"   ✅ 创建成功!")
    print(f"   ID: {kb_id}")
    print(f"   名称: {data['data']['name']}")
    return kb_id


async def test_insert_texts(kb_id: str):
    """测试 3: 插入文本"""
    separator("测试 3: 插入知识文本")

    async with httpx.AsyncClient(timeout=60) as client:
        for i, item in enumerate(TEST_KNOWLEDGE_TEXTS, 1):
            print(f"\n   [{i}/{len(TEST_KNOWLEDGE_TEXTS)}] 插入: {item['description']}...")
            resp = await client.post(
                f"{COSIGHT_BASE}/deep-research/kb/{kb_id}/documents/text",
                json={"text": item["text"], "description": item["description"]}
            )
            data = resp.json()
            if data.get("code") == 0:
                print(f"          ✅ 成功 (字数: {len(item['text'])})")
            else:
                print(f"          ❌ 失败: {data.get('msg')}")

    print(f"\n   ⏳ 等待 LightRAG 后台索引处理 (15秒)...")
    await asyncio.sleep(15)
    print(f"   ✅ 索引等待完成")


async def test_query(kb_id: str):
    """测试 4: 查询知识库"""
    separator("测试 4: 查询知识库")

    async with httpx.AsyncClient(timeout=120) as client:
        for i, question in enumerate(TEST_QUERIES, 1):
            print(f"\n   ━━━ 查询 {i}/{len(TEST_QUERIES)} ━━━")
            print(f"   ❓ 问题: {question}")

            try:
                resp = await client.post(
                    f"{COSIGHT_BASE}/deep-research/kb/{kb_id}/query",
                    json={"question": question, "mode": "hybrid", "only_context": False}
                )
                data = resp.json()

                if data.get("code") == 0:
                    result = data.get("data", {})
                    if isinstance(result, str):
                        answer = result
                    elif isinstance(result, dict):
                        answer = result.get("response", json.dumps(result, ensure_ascii=False))
                    else:
                        answer = str(result)

                    # 截取前 300 个字符展示
                    preview = answer[:300] + ("..." if len(answer) > 300 else "")
                    print(f"   💡 回答: {preview}")
                else:
                    print(f"   ❌ 查询失败: {data.get('msg')}")

            except Exception as e:
                print(f"   ❌ 查询异常: {e}")


async def test_list_kb():
    """测试 5: 列出所有知识库"""
    separator("测试 5: 列出所有知识库")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{COSIGHT_BASE}/deep-research/kb/list")
        data = resp.json()

    kbs = data.get("data", {}).get("knowledge_bases", [])
    print(f"\n   共有 {len(kbs)} 个知识库:")
    for kb in kbs:
        print(f"   • [{kb['id']}] {kb['name']} ({kb.get('doc_count', 0)} 篇文档)")

    return kbs


async def test_delete_kb(kb_id: str, kb_name: str):
    """测试 6: 删除知识库"""
    separator("测试 6: 清理 — 删除测试知识库")

    print(f"\n   删除知识库: {kb_name} ({kb_id})")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(f"{COSIGHT_BASE}/deep-research/kb/{kb_id}")
        data = resp.json()

    if data.get("code") == 0:
        print(f"   ✅ 删除成功")
    else:
        print(f"   ❌ 删除失败: {data.get('msg')}")


async def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║     Co-Sight 知识库系统 (LightRAG) 完整测试             ║")
    print("╚══════════════════════════════════════════════════════════╝")

    # 1. 健康检查
    ok = await test_health_check()
    if not ok:
        print("\n❌ 服务未就绪，请先启动 LightRAG 和 Co-Sight 后重试。")
        sys.exit(1)

    # 2. 创建知识库
    kb_id = await test_create_kb()
    if not kb_id:
        print("\n❌ 创建知识库失败，终止测试。")
        sys.exit(1)

    try:
        # 3. 插入文本
        await test_insert_texts(kb_id)

        # 4. 查询
        await test_query(kb_id)

        # 5. 列出所有知识库
        await test_list_kb()

    finally:
        # 6. 清理
        should_delete = input("\n   是否删除刚才创建的测试知识库? (y/n, 默认y): ").strip().lower()
        if should_delete != "n":
            await test_delete_kb(kb_id, f"自动测试KB")
        else:
            print(f"\n   ℹ️  保留知识库 {kb_id}，可在前端管理面板中手动删除。")

    separator("测试完成")
    print("\n   🎉 全部测试已完成！")
    print(f"   知识库系统运行正常。\n")


if __name__ == "__main__":
    asyncio.run(main())
