import os
import json
import logging
import requests
from typing import List, Optional
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, OpenAIChatCompletion, OpenAIChatPromptExecutionSettings
from semantic_kernel.prompt_template import InputVariable, PromptTemplateConfig

logger = logging.getLogger(__name__)

class DescriptionRequest(BaseModel):
    name: str
    tags: List[str]

description = APIRouter(
    prefix="/generate",
    tags=["generation"]
)

async def get_kernel():
    kernel = Kernel()

    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        logger.info(f"Loading environment from: {env_path}")
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        logger.warning("No .env file found! Using system environment variables.")
    
    use_local_llm = os.environ.get("USE_LOCAL_LLM", "False").lower() == "true"

    if use_local_llm:
        logger.info("Using local LLM model")
        base_url = os.environ.get("LOCAL_LLM_ENDPOINT")
        
        if not base_url:
            raise ValueError("LOCAL_LLM_ENDPOINT must be provided")
        
        return kernel

    use_azure = os.environ.get("USE_AZURE_OPENAI", "False").lower() == "true"
    use_azure_ad = os.environ.get("USE_AZURE_AD", "False").lower() == "true"
    
    if use_azure:
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        
        if not deployment or not endpoint:
            raise ValueError("Azure OpenAI deployment name and endpoint must be provided")
        
        logger.info(f"Using Azure OpenAI: {deployment} at {endpoint}")
    
        if use_azure_ad:
            logger.info("Using Azure AD authentication")
            token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")

            kernel.add_service(
                AzureChatCompletion(
                    deployment_name=deployment,
                    endpoint=endpoint,
                    ad_token_provider=token_provider,
                ),
            )
        else:
            api_key = os.environ.get("OPENAI_API_KEY")
            logger.info("Using Azure OpenAI with API key")
            if not api_key:
                raise ValueError("OpenAI API key must be provided for Azure OpenAI without AD authentication")        

            kernel.add_service(
                AzureChatCompletion(
                    deployment_name=deployment,
                    endpoint=endpoint,
                    api_key=api_key
                )
            )
    else:
        api_key = os.environ.get("OPENAI_API_KEY")
        org_id = os.environ.get("OPENAI_ORG_ID")
        
        if not api_key:
            raise ValueError("OpenAI API key must be provided")
        
        if not org_id:
            raise ValueError("OpenAI organization ID must be provided")
        
        logger.info("Using OpenAI API")
        
        kernel.add_service(
            OpenAIChatCompletion(
                ai_model_id="gpt-3.5-turbo",
                api_key=api_key,
                org_id=org_id
            )
        )
    return kernel

@description.post("/description", operation_id="generate_description")
async def generate_description(request: DescriptionRequest, kernel: Kernel = Depends(get_kernel)):
    """
    Generate a product description based on the product name and tags
    """
    try:
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if os.path.exists(env_path):
            logger.info(f"Loading environment from: {env_path}")
            load_dotenv(dotenv_path=env_path, override=True)
        else:
            logger.warning("No .env file found! Using system environment variables.")
        
        use_local_llm = os.environ.get("USE_LOCAL_LLM", "False").lower() == "true"

        if use_local_llm:
            endpoint = os.environ.get("LOCAL_LLM_ENDPOINT")
            if not endpoint:
                raise ValueError("LOCAL_LLM_ENDPOINT must be provided")
            
            model_name = os.getenv("LOCAL_LLM_MODEL_NAME")
            if not model_name:
                raise ValueError("LOCAL_LLM_MODEL_NAME must be provided")
        
            name: str = request.name
            tags: List = ",".join(request.tags)

            temperature = 1.0
            top_p = 1
            max_length = 200
            repetition_penalty = 1.0
            length_penalty = 1.0

            if endpoint.endswith("v1/chat/completions"):
                prompt = f"Describe this pet store product using joyful, playful, and enticing language.\nProduct name: {name}\ntags: {tags}\""
                payload = {
                    "model": model_name,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": temperature,
                    "top_p": top_p,
                    "max_tokens": max_length,
                    "length_penalty": length_penalty,
                    "repetition_penalty": repetition_penalty
                }

                headers = {"Content-Type": "application/json"}
                response = requests.request("POST", endpoint, headers=headers, json=payload)            
                
                # convert response.text to json
                result = json.loads(response.content)
                result = result["choices"][0]["message"]["content"]
                return {"description": result}
            else:
                prompt = f"<|user|>Describe this pet store product using joyful, playful, and enticing language.\nProduct name: {name}\ntags: {tags}<|end|><|assistant|>\""
                payload = {
                    "prompt": prompt,
                    "return_full_text": "false",
                    "clean_up_tokenization_spaces": "true",
                    "generate_kwargs": {
                        "temperature": temperature,
                        "max_length": max_length,
                        "repetition_penalty": repetition_penalty,
                        "top_p": top_p
                    }
                }
                
                headers = {"Content-Type": "application/json"}
                response = requests.request("POST", endpoint, headers=headers, json=payload)            
                
                # convert response.text to json
                result = json.loads(response.content)
                result = result["Result"]
                
                # remove all double quotes
                if "\"" in result:
                    result = result.replace("\"", "")

                # remove all leading and trailing whitespace
                result = result.strip()
                return {"description": result}
        else:
            execution_settings = OpenAIChatPromptExecutionSettings(
                max_tokens=1000,
                temperature=0.5,
                top_p=0.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
            )
            
            prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "description_prompt.txt")
            
            if not os.path.exists(prompt_path):
                raise FileNotFoundError(f"Prompt file not found at {prompt_path}")
                
            with open(prompt_path, "r") as file:
                prompt_template = file.read()
            
            prompt_template_config = PromptTemplateConfig(
                template=prompt_template,
                name="description",
                template_format="semantic-kernel",
                input_variables=[
                    InputVariable(name="name", description="The name of the product", is_required=True),
                    InputVariable(name="tags", description="The tags for the product", is_required=True),
                ],
                execution_settings=execution_settings,
            )

            description_function = kernel.add_function(
                function_name="descriptionFunction",
                plugin_name="descriptionPlugin",
                prompt_template_config=prompt_template_config,
            )
            
            result = await kernel.invoke(description_function, name=request.name, tags = ", ".join(request.tags))

            if not result or not result.value:
                raise ValueError("No response from generative AI")

            return {"description": result.value[0].content}
    except Exception as e:
        logger.error(f"Error generating description: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error generating description: {str(e)}")