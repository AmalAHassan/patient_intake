import json
import redis
from anthropic import Anthropic
from config import settings

redis_client = redis.from_url(settings.redis_url)
anthropic_client = Anthropic(api_key=settings.anthropic_api_key)

SYSTEM_PROMPT = """You are a friendly patient intake assistant. Collect these fields one at a time:
1. Full name
2. Date of birth (MM/DD/YYYY)
3. Phone number
4. Email
5. Insurance member ID
6. Insurance payer name
7. Reason for visit

Ask one question at a time. Be warm and concise. After collecting each field, acknowledge what you received and move to the next.

When you have all 7 fields, respond with EXACTLY this JSON and nothing else:
{"status": "complete", "data": {"name": "", "dob": "", "phone": "", "email": "", "insurance_id": "", "payer": "", "reason": ""}}

Until then, continue conversing naturally."""


async def chat(session_id: str, user_message: str) -> dict:
    """Process user message and return Claude's response."""
    history_key = f"session:{session_id}:history"
    collected_key = f"session:{session_id}:collected"

    history_json = redis_client.get(history_key)
    history = json.loads(history_json) if history_json else []

    history.append({"role": "user", "content": user_message})

    response = anthropic_client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=history,
    )

    assistant_message = response.content[0].text
    history.append({"role": "assistant", "content": assistant_message})

    redis_client.setex(history_key, 86400, json.dumps(history))

    result = {
        "reply": assistant_message,
        "status": "collecting",
        "data": None,
    }

    if '{"status": "complete"' in assistant_message:
        try:
            json_str = assistant_message[
                assistant_message.find('{"status": "complete"') :
            ]
            parsed = json.loads(json_str)
            if parsed.get("status") == "complete":
                result["status"] = "complete"
                result["data"] = parsed.get("data", {})
                redis_client.setex(collected_key, 86400, json.dumps(result["data"]))
        except json.JSONDecodeError:
            pass

    return result


async def get_session_data(session_id: str) -> dict:
    """Get collected data for a session."""
    collected_key = f"session:{session_id}:collected"
    data_json = redis_client.get(collected_key)
    return json.loads(data_json) if data_json else {}
