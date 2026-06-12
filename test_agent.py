from composer import Agent, Thread, HumanMessage
from pathlib import Path
import os
from dotenv import load_dotenv
from webgent.config import get_settings
import asyncio
load_dotenv()

BASE_URL = os.getenv("BASE_URL")
API_KEY = os.getenv("API_KEY")

settings = get_settings()
async def main():
    agent = Agent(
        model=settings.agent.vlm_model,
        base_url=BASE_URL,
        api_key=API_KEY,
    )

    thread = Thread()
    # HumanMessage("Hello, how are you?") | thread

    # resp = thread | agent

    # print("<======General Response======>")
    # print(resp.content)

    img_path = Path(__file__).parent / "media" / "0076931a-e53f-437e-918f-8e377bfe75f2.png"

    HumanMessage("""
you will we given an recaptcha image with grid cell
instruction was at top of the image. as per that provide the cell buttons to click with 100% surety.

| Position | Ref ID |
|----------|--------|
| **Row 1** | |
| Cell 1 (top-left) | `f4e15` |
| Cell 2 (top-center) | `f4e18` |
| Cell 3 (top-right) | `f4e21` |
| **Row 2** | |
| Cell 1 (middle-left) | `f4e25` |
| Cell 2 (middle-center) | `f4e28` |
| Cell 3 (middle-right) | `f4e31` |
| **Row 3** | |
| Cell 1 (bottom-left) | `f4e35` |
| Cell 2 (bottom-center) | `f4e38` |
| Cell 3 (bottom-right) | `f4e41` |
provide the cell buttons to click with 100% surety.
    """).attach(img_path) | thread

    resp = await (thread | agent)

    print("<======Image Attached Response======>")
    print(resp.content)

if __name__ == "__main__":
    asyncio.run(main())