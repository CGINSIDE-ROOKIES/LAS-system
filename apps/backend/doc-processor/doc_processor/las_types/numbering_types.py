from pydantic import BaseModel


class NumberMatch(BaseModel):
    val: str
    span: tuple[int, int]
