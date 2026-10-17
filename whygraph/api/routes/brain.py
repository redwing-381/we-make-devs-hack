"""Company Brain Q&A. Owner: F-B7 (feat/brain-agent)."""

from fastapi import APIRouter
from pydantic import BaseModel

from whygraph.api.routes._stub import not_implemented

router = APIRouter(prefix="/brain", tags=["brain"])


class AskIn(BaseModel):
    question: str


@router.post("/ask")
def ask(body: AskIn) -> dict:
    raise not_implemented("F-B7 feat/brain-agent")
