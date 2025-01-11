# routers/health.py

from fastapi import APIRouter
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health", summary="Health Check Endpoint")
def health_check():
    logger.info("Health check endpoint was called.")
    return {"status": "OK"}
