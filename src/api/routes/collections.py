from __future__ import annotations

from fastapi import APIRouter

from src.core.vector_store import list_collections

router = APIRouter(prefix="/collections", tags=["collections"])


@router.get("")
async def get_collections():
    return {"collections": list_collections()}
