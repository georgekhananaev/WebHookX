# main.py

import logging
from fastapi import FastAPI
from logging_config import setup_logging

# Import and include routers
from routers.health import router as health_router
from routers.tests import router as test_command_router
from routers.webhook import router as webhook_router
from routers.deploy import router as deploy_router

# Initialize logging
setup_logging()
logger = logging.getLogger(__name__)
logger.info("Starting the WebHookX application...")

# Initialize FastAPI app
app = FastAPI(title="WebHookX", description="Automated GitHub Repository Deployment Tool", version="1.0.0")

app.include_router(health_router)
app.include_router(test_command_router)
app.include_router(webhook_router)
app.include_router(deploy_router)


# Optional root endpoint
@app.get("/", summary="Root Endpoint")
def read_root():
    return {"message": "Welcome to WebHookX - Your Deployment Automation Tool!"}