import os
import json
import logging
from typing import Any, List, Dict
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response, JSONResponse
from openai import AzureOpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class ImageRequest(BaseModel):
    name: str
    description: str

# Create router with prefix
image = APIRouter(
    prefix="/generate",
    tags=["generation"]
)

@image.post("/image", operation_id="generate_image")
async def generate_image(request: ImageRequest):
    """
    Generate a product image based on the product name and description
    """
    try:
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if os.path.exists(env_path):
            logger.info(f"Loading environment from: {env_path}")
            load_dotenv(dotenv_path=env_path, override=True)
        else:
            logger.warning("No .env file found! Using system environment variables.")

        endpoint = os.environ.get("AZURE_OPENAI_DALLE_ENDPOINT") or os.environ.get("AZURE_OPENAI_ENDPOINT")
        if not endpoint:
            raise ValueError("AZURE_OPENAI_DALLE_ENDPOINT or AZURE_OPENAI_ENDPOINT must be provided")
        
        model_deployment_name = os.environ.get("AZURE_OPENAI_DALLE_DEPLOYMENT_NAME")
        if not os.environ.get("AZURE_OPENAI_DALLE_DEPLOYMENT_NAME"):
            raise ValueError("AZURE_OPENAI_DALLE_DEPLOYMENT_NAME must be provided")

        api_version = os.environ.get("AZURE_OPENAI_API_VERSION")
        if not api_version:
            raise ValueError("AZURE_OPENAI_API_VERSION must be provided")
        
        name: str = request.name
        description: List = request.description
        token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
        
        client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
        )

        result = client.images.generate(
            model=model_deployment_name,
            prompt="Generate a cute photo realistic image of a product in its packaging in front of a plain background for a product called <"+ name + "> with a description <" + description + "> to be sold in an online pet supply store",
            n=1
        )

        json_response = json.loads(result.model_dump_json())

        return JSONResponse(content={"image": json_response["data"][0]["url"]}, status_code=status.HTTP_200_OK)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating image: {str(e)}")