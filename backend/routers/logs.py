"""Conversation / capture / print logs for the Admin dashboard."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

import database as db
from security import require_admin

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def read_logs(
    type: str | None = Query(None, description="conversation|capture|print|enhance|face|error|system"),
    limit: int = Query(100, le=500),
    offset: int = 0,
    _: bool = Depends(require_admin),
):
    return {"logs": db.list_logs(log_type=type, limit=limit, offset=offset)}


@router.delete("")
async def delete_logs(type: str | None = None, _: bool = Depends(require_admin)):
    removed = db.clear_logs(log_type=type)
    return {"ok": True, "removed": removed}
