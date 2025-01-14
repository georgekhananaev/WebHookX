# main.py

import logging
from fastapi import FastAPI
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

from config import DEBUG_MODE
from logging_config import setup_logging

# Routers
from routers.health import router as health_router
from routers.tests import router as test_command_router
from routers.webhook import router as webhook_router
from routers.deploy import router as deploy_router

# Initialize logging once
setup_logging(DEBUG_MODE)

logger = logging.getLogger(__name__)
logger.info("Starting the WebHookX application...")

app = FastAPI(
    title="WebHookX",
    description="Automated GitHub Repository Deployment Tool with Multi-Server Chain",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(health_router)
app.include_router(test_command_router)
app.include_router(webhook_router)
app.include_router(deploy_router)


@app.get("/openapi.json", include_in_schema=False)
def get_open_api_endpoint():
    return get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes
    )


@app.get("/docs", include_in_schema=False)
def custom_swagger_ui():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=app.title,
        swagger_ui_parameters={"syntaxHighlight.theme": "obsidian"},
        swagger_css_url="/static/swagger_ui_dark.min.css"
    )


@app.get("/redoc", include_in_schema=False)
def custom_redoc_ui():
    return get_redoc_html(
        openapi_url="/openapi.json",
        title=app.title
    )
