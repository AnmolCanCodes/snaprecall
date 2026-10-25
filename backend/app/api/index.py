"""Indexing queue status and controls."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.schemas import ErrorResponse, IndexStatus, ScanResult
from app.services.watcher import scan_folder
from app.services.worker import IndexWorker

router = APIRouter(
    prefix="/index", tags=["index"], responses={503: {"model": ErrorResponse}}
)


def get_worker(request: Request) -> IndexWorker:
    """Return the worker created by the app lifespan."""
    worker = getattr(request.app.state, "worker", None)
    if worker is None:
        raise HTTPException(status_code=503, detail="Index worker is not running")
    return worker


WorkerDep = Annotated[IndexWorker, Depends(get_worker)]


@router.get("/status", response_model=IndexStatus)
async def index_status(worker: WorkerDep) -> IndexStatus:
    """Queue counts, current file and worker state."""
    return await worker.status()


@router.post("/scan", response_model=ScanResult)
async def index_scan(worker: WorkerDep) -> ScanResult:
    """Scan the screenshots folder now and wake the worker."""
    result = await asyncio.to_thread(scan_folder)
    worker.notify()
    return result


@router.post("/pause", response_model=IndexStatus)
async def index_pause(worker: WorkerDep) -> IndexStatus:
    """Pause the worker after the current image."""
    worker.pause()
    return await worker.status()


@router.post("/resume", response_model=IndexStatus)
async def index_resume(worker: WorkerDep) -> IndexStatus:
    """Resume the worker."""
    worker.resume()
    return await worker.status()