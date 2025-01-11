import logging
from fastapi import FastAPI
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

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

# Initialize FastAPI app with docs disabled
app = FastAPI(
    title="WebHookX",
    description="Automated GitHub Repository Deployment Tool",
    version="1.0.0",
    docs_url=None,  # Disable default /docs
    redoc_url=None,  # Disable default /redoc
    openapi_url=None,  # Disable default /openapi.json

)

# Mount static folder containing swagger_ui_dark.min.css
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
app.include_router(health_router)
app.include_router(test_command_router)
app.include_router(webhook_router)
app.include_router(deploy_router)


# Optional root endpoint
# @app.get("/", summary="Root Endpoint")
# def read_root():
#     return {"message": "Welcome to WebHookX - Your Deployment Automation Tool!"}


# 1. Serve your OpenAPI schema at /openapi.json
@app.get("/openapi.json", include_in_schema=False)
def get_open_api_endpoint():
    return get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes
    )


# 2. Custom dark-theme Swagger UI at /docs
@app.get("/docs", include_in_schema=False)
def custom_swagger_ui():
    """
    Custom Swagger UI that uses a dark theme.
    The swagger CSS can be hosted locally in /static or from a CDN.
    """
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=app.title,
        swagger_ui_parameters={
            "syntaxHighlight.theme": "obsidian",  # Dark code blocks
        },
        # Provide a local or external URL for swagger_ui_dark.min.css
        swagger_css_url="/static/swagger_ui_dark.min.css"
    )


# # 3. (Optional) Custom ReDoc at /redoc
# @app.get("/redoc", include_in_schema=False)
# def custom_redoc_ui():
#     return get_redoc_html(
#         openapi_url="/openapi.json",
#         title=app.title
#     )
