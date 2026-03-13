import os
import sys

# Add current dir to python_path to allow importing app
sys.path.insert(0, os.path.abspath('.'))

from dotenv import load_dotenv
load_dotenv()

print("--- Testing Tavily Raw Client ---")
try:
    from tavily import TavilyClient
    api_key = os.getenv("TAVILY_API_KEY")
    print(f"Loaded API KEY: {api_key}")
    client = TavilyClient(api_key=api_key)
    res = client.search("Hello world", max_results=1)
    print("✅ Raw client search success!")
    print(res)
except Exception as e:
    print(f"❌ Raw client test failed: {e}")

print("\n--- Testing SearchToolkit ---")
try:
    from app.cosight.tool.search_toolkit import SearchToolkit
    toolkit = SearchToolkit()
    res2 = toolkit.tavily_search("Current weather in London", num_results=1)
    print("✅ SearchToolkit search success!")
    print(res2)
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"❌ SearchToolkit test failed: {e}")
