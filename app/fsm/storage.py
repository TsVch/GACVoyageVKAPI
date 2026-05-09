import json
from dataclasses import dataclass, field

import redis.asyncio as redis

from app.config import get_settings
from app.fsm.states import DialogState


@dataclass
class SessionData:
    state: DialogState = DialogState.START
    payload: dict = field(default_factory=dict)


class FSMStorage:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._memory: dict[int, SessionData] = {}
        self._redis = redis.from_url(self.settings.redis_url, decode_responses=True) if self.settings.redis_url else None

    async def get(self, user_id: int) -> SessionData:
        if self._redis:
            data = await self._redis.get(f"fsm:{user_id}")
            if data:
                parsed = json.loads(data)
                return SessionData(state=DialogState(parsed["state"]), payload=parsed.get("payload", {}))
        return self._memory.get(user_id, SessionData())

    async def set(self, user_id: int, session: SessionData) -> None:
        if self._redis:
            await self._redis.set(
                f"fsm:{user_id}",
                json.dumps({"state": session.state.value, "payload": session.payload}),
                ex=3600,
            )
        self._memory[user_id] = session

    async def clear(self, user_id: int) -> None:
        if self._redis:
            await self._redis.delete(f"fsm:{user_id}")
        self._memory.pop(user_id, None)