import asyncio
import os
import sys

# Add current dir to python_path to allow importing app
sys.path.insert(0, os.path.abspath('.'))

from dotenv import load_dotenv
load_dotenv()

# We extract the core components used in your WebToolkit
from browser_use import Agent
from browser_use.browser import BrowserSession, BrowserProfile
from browser_use.llm import ChatOpenAI

async def test_native_browser_use():
    print("--- Testing Browser Use Automation ---")
    
    # 1. Provide LLM Configuration (From your .env / config)
    # the browser_use library requires an LLM to drive the agent
    # this mimics how WebToolkit sets up ChatOpenAI with Qwen or GLM
    api_key = os.getenv("BROWSER_API_KEY") or os.getenv("API_KEY")
    base_url = os.getenv("BROWSER_API_BASE_URL") or os.getenv("API_BASE_URL")
    model_name = os.getenv("BROWSER_MODEL_NAME") or os.getenv("MODEL_NAME", "qwen3.5-plus")

    if not api_key:
        print("❌ Missing API_KEY in .env file")
        return

    print(f"Using LLM Model: {model_name}")

    llm = ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=0.0
    )

    # 2. Configure Browser Profile
    # Here we use headless=False so you can visually see the browser pop up and work
    profile = BrowserProfile(
        headless=False,
        disable_security=True,
        keep_alive=False
    )
    browser_session = BrowserSession(browser_profile=profile)
    await browser_session.start()

    # 3. Create the Agent
    task_prompt = "Go to https://www.bing.com, search for 'Hello World', and return the title of the first search result."
    print(f"\nTask: {task_prompt}")
    
    agent = Agent(
        task=task_prompt,
        llm=llm,
        browser_session=browser_session,
        use_vision=False,
        flash_mode=True
    )

    try:
        # 4. Run the Agent
        result = await agent.run()
        final_result = result.final_result()
        print("\n✅ Browser execution completed!")
        print(f"Final Output: {final_result}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n❌ Browser automation failed: {e}")
    finally:
        # Clean up
        await browser_session.kill()

if __name__ == "__main__":
    asyncio.run(test_native_browser_use())
