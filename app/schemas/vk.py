from pydantic import BaseModel


class VKObjectMessage(BaseModel):
    from_id: int
    text: str = ""
    payload: str | None = None


class VKCallbackEvent(BaseModel):
    type: str
    object: dict
