import aiohttp
from config import config
from utils.logger import log_agent_action

# DeepSeek API (OpenAI-compatible). Model is configurable via DEEPSEEK_MODEL;
# default deepseek-v4-flash (non-thinking) — fast and cheap for short RU proposals.
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


async def chat_completion(messages: list[dict], timeout: int = 60) -> str:
    if not config.DEEPSEEK_API_KEY:
        log_agent_action("DeepSeek", "API key not configured", level="WARNING")
        return "DeepSeek API key not configured."

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                DEEPSEEK_URL,
                headers={
                    "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"model": config.DEEPSEEK_MODEL, "messages": messages},
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log_agent_action("DeepSeek", f"❌ HTTP {resp.status}: {body[:300]}", level="ERROR")
                    raise RuntimeError(f"DeepSeek HTTP {resp.status}: {body[:200]}")
                data = await resp.json()
                if "choices" not in data:
                    log_agent_action("DeepSeek", f"❌ No choices in response: {str(data)[:300]}", level="ERROR")
                    raise RuntimeError(f"No choices: {data}")
                content = data["choices"][0]["message"]["content"]
                return (content or "").strip()
    except Exception as e:
        log_agent_action("DeepSeek", f"❌ API error: {e}", level="ERROR")
        raise
