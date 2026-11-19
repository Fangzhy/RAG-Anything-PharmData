import os

import httpx
from dotenv import dotenv_values

from pharm.catalog import ROOT


class ProviderUnavailable(RuntimeError):
    pass


def settings():
    local = dotenv_values(ROOT / ".env")
    key = next((os.getenv(k) or local.get(k) for k in ("OPENROUTER_API_KEY","OPEN_ROUTER_API") if os.getenv(k) or local.get(k)), None)
    model = os.getenv("OPENROUTER_MODEL") or local.get("OPENROUTER_MODEL") or "openrouter/free"
    return key, model


async def completion(prompt, system_prompt=None, history_messages=None, **kwargs):
    key, model = settings()
    if not key:
        raise ProviderUnavailable("Configure OPENROUTER_API_KEY or OPEN_ROUTER_API to generate answers.")
    if not (model.endswith(":free") or model == "openrouter/free"):
        raise ProviderUnavailable("Choose a free OpenRouter model in OPENROUTER_MODEL.")
    messages = [{"role":"system","content":system_prompt}] if system_prompt else []
    messages.extend(history_messages or [])
    messages.append({"role":"user","content":prompt})
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post("https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": "Bearer "+key},
                json={"model":model,"messages":messages,"temperature":0,"max_tokens":1000})
    except httpx.HTTPError:
        raise ProviderUnavailable("OpenRouter could not be reached. Retrieved evidence is available.") from None
    if response.status_code != 200:
        raise ProviderUnavailable(f"OpenRouter returned HTTP {response.status_code}. Retrieved evidence is available.")
    try:
        answer = response.json()["choices"][0]["message"]["content"]
        if not isinstance(answer,str) or not answer.strip():
            raise ValueError
        return answer
    except (ValueError, KeyError, IndexError, TypeError):
        raise ProviderUnavailable("OpenRouter returned an empty or incomplete response.") from None
