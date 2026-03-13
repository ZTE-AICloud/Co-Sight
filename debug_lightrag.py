import asyncio
import os
import shutil
from lightrag import LightRAG
from lightrag.llm.openai import openai_complete_if_cache, openai_embed

async def debug_embedding():
    print("Clearing debug storage...")
    if os.path.exists("./rag_storage_debug"):
        shutil.rmtree("./rag_storage_debug")
    os.makedirs("./rag_storage_debug")

    print("Initializing LightRAG...")
    os.environ["LLM_BINDING"] = "openai"
    os.environ["LLM_BINDING_HOST"] = "https://coding.dashscope.aliyuncs.com/v1"
    os.environ["LLM_BINDING_API_KEY"] = "sk-sp-75c1757bbe3048799c0028481bfda015"
    os.environ["LLM_MODEL"] = "glm-5"
    
    os.environ["EMBEDDING_BINDING"] = "openai"
    os.environ["EMBEDDING_BINDING_HOST"] = "https://api.siliconflow.cn/v1"
    os.environ["EMBEDDING_BINDING_API_KEY"] = "sk-roqvydfziqubtdqjrgzjgovmpaecrttvtszjvakrefytvewb"
    os.environ["EMBEDDING_MODEL"] = "Qwen/Qwen3-Embedding-4B"
    os.environ["EMBEDDING_DIM"] = "2560"

    # NOTE: In v1.4.10, LightRAG's llm_kwargs doesn't exist, we must inject API keys to model_func.
    rag = LightRAG(
        working_dir="./rag_storage_debug",
        llm_model_func=openai_complete_if_cache,
        llm_model_name=os.environ["LLM_MODEL"],
        llm_model_max_async=4,
        embedding_func=openai_embed,
        embedding_batch_num=10,
        embedding_func_max_async=8,
    )
    
    print("\n--- Testing Document Insertion & Indexing ---")
    texts = ["Quantum supremacy is achieved by Google using the Sycamore processor."]
    try:
        await rag.ainsert(texts)
        print("Insertion successful!")
    except Exception as e:
        print(f"!!! Insertion failed !!!\n{e}")

    print("\n--- Testing Query ---")
    try:
        res = await rag.aquery("Which company achieved quantum supremacy?", param={"mode": "hybrid"})
        print(f"Query Results:\n{res}")
    except Exception as e:
        print(f"!!! Query failed !!!\n{e}")

if __name__ == "__main__":
    asyncio.run(debug_embedding())
