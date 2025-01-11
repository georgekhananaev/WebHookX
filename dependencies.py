# dependencies.py

from fastapi import Header, HTTPException, status, Depends
import logging
from config import DEPLOY_API_KEY, LIST_FILES_API_KEY

logger = logging.getLogger(__name__)


def get_deploy_api_key(api_key: str = Header(..., alias="X-API-Key")):
    if api_key != DEPLOY_API_KEY:
        logger.warning("Invalid API Key for manual deployment.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")
    return api_key


def get_list_files_api_key(api_key: str = Header(..., alias="X-API-Key")):
    if api_key != LIST_FILES_API_KEY:
        logger.warning("Invalid API Key for list files or test command.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")
    return api_key

# # dependencies.py
#
# from fastapi import Header, HTTPException, status, Depends
# import logging
# from config import DEPLOY_API_KEY, LIST_FILES_API_KEY
#
# logger = logging.getLogger(__name__)
#
#
# def get_deploy_api_key(api_key: str = Header(..., alias="X-API-Key")):
#     if api_key != DEPLOY_API_KEY:
#         logger.warning("Invalid API Key for manual deployment.")
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")
#     return api_key
#
#
# def get_list_files_api_key(api_key: str = Header(..., alias="X-API-Key")):
#     if api_key != LIST_FILES_API_KEY:
#         logger.warning("Invalid API Key for list files or test command.")
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")
#     return api_key
