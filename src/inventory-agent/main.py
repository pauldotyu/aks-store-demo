import contextlib
import json
import logging
import os
import re
from typing import Any

import requests
from a2a.helpers import new_task_from_user_message
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Part,
    TaskState,
)
from agent_framework import Agent
from agent_framework.a2a import A2AExecutor
from agent_framework.observability import configure_otel_providers
from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

load_dotenv()

INVENTORY_SERVICE_URL = os.environ.get(
    "INVENTORY_SERVICE_URL", "http://inventory-service:7001"
).rstrip("/")
TIMEOUT_SECONDS = float(os.environ.get("INVENTORY_AGENT_HTTP_TIMEOUT_SECONDS", "10"))
APP_VERSION = os.environ.get("APP_VERSION", "0.1.0")
PUBLIC_BASE_URL = os.environ.get(
    "INVENTORY_AGENT_PUBLIC_BASE_URL", "http://inventory-agent:7002"
).rstrip("/")
logger = logging.getLogger("inventory-agent")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


if _env_bool("ENABLE_INSTRUMENTATION", False):
    configure_otel_providers(enable_sensitive_data=False)


def _build_chat_client() -> OpenAIChatClient:
    use_passwordless = _env_bool("USE_WORKLOAD_IDENTITY_AUTH", False)
    if not use_passwordless:
        # OPENAI_API_KEY-based path (also supports local OpenAI-compatible endpoints with OPENAI_API_KEY=none)
        return OpenAIChatClient()

    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    model = os.environ.get("AZURE_OPENAI_CHAT_MODEL") or os.environ.get(
        "OPENAI_CHAT_MODEL"
    )
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION")
    if not azure_endpoint:
        raise RuntimeError(
            "USE_WORKLOAD_IDENTITY_AUTH=true requires AZURE_OPENAI_ENDPOINT"
        )
    if not model:
        raise RuntimeError(
            "USE_WORKLOAD_IDENTITY_AUTH=true requires AZURE_OPENAI_CHAT_MODEL or OPENAI_CHAT_MODEL"
        )
    if not api_version:
        raise RuntimeError(
            "USE_WORKLOAD_IDENTITY_AUTH=true requires AZURE_OPENAI_API_VERSION"
        )

    return OpenAIChatClient(
        model=model,
        azure_endpoint=azure_endpoint,
        api_version=api_version,
        credential=DefaultAzureCredential(),
    )


def _request(method: str, path: str, payload=None) -> Any:
    url = f"{INVENTORY_SERVICE_URL}{path}"
    try:
        response = requests.request(method, url, json=payload, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as err:
        raise RuntimeError(f"inventory service request failed: {err}") from err

    if not response.ok:
        raise RuntimeError(
            f"inventory service {method} {path} failed: {response.status_code} {response.text}"
        )

    if response.content:
        return response.json()
    return {}


def check_stock(product_id: int) -> dict:
    """Return inventory state for one product."""
    return _request("GET", f"/inventory/{product_id}")


def reserve_stock(
    product_id: int,
    quantity: int,
    order_id: str,
    idempotency_key: str,
    workflow_id: str,
) -> dict:
    """Reserve stock for a product and return reservation result."""
    payload = {
        "orderId": order_id,
        "quantity": quantity,
        "idempotencyKey": idempotency_key,
        "workflowId": workflow_id,
    }
    return _request("POST", f"/inventory/{product_id}/reserve", payload)


def create_reorder_proposal(
    product_id: int, quantity: int, workflow_id: str, reason: str
) -> dict:
    """Create a reorder proposal for one product."""
    payload = {
        "productId": product_id,
        "quantity": quantity,
        "workflowId": workflow_id,
        "reason": reason,
    }
    return _request("POST", "/proposals/reorder", payload)


def get_reorder_proposal(proposal_id: str) -> dict:
    """Get one reorder proposal by id."""
    return _request("GET", f"/proposals/{proposal_id}")


def process_order_inventory(order_payload_json: str) -> str:
    """
    Deterministically reserve inventory for order items and return JSON results.
    """
    payload_text = order_payload_json.strip()

    # Handle both raw JSON payloads and prompts that embed the JSON object.
    if not payload_text.startswith("{"):
        match = re.search(r"\{.*\}", payload_text, re.DOTALL)
        if not match:
            raise ValueError(
                "Expected input containing a JSON object with orderId and items"
            )
        payload_text = match.group(0)

    payload = json.loads(payload_text)
    order_id = payload["orderId"]
    workflow_id = payload.get("workflowId") or order_id
    correlation_id = payload.get("correlationId")
    items = payload["items"]

    reservations = []
    proposal_ids: set[str] = set()
    for item in items:
        product_id = int(item["productId"])
        quantity = int(item["quantity"])
        idempotency_key = f"{order_id}:{product_id}:{quantity}"
        reservation = reserve_stock(
            product_id=product_id,
            quantity=quantity,
            order_id=order_id,
            idempotency_key=idempotency_key,
            workflow_id=workflow_id,
        )
        reservations.append(reservation)
        proposal_id = reservation.get("proposalId")
        if proposal_id:
            proposal_ids.add(proposal_id)

    result = {
        "orderId": order_id,
        "workflowId": workflow_id,
        "correlationId": correlation_id,
        "reservations": reservations,
        "proposalIds": sorted(proposal_ids),
    }
    return json.dumps(result)


# Standards-compliant MCP server (streamable HTTP)
mcp = FastMCP(name="InventoryTools", stateless_http=True)
# Keep the final external endpoint at /mcp after Starlette mount.
mcp.settings.streamable_http_path = "/"


@mcp.tool()
def mcp_check_stock(product_id: int) -> dict:
    """check_stock(product_id): Returns inventory status for a product."""
    return check_stock(product_id)


@mcp.tool()
def mcp_reserve_stock(
    product_id: int,
    quantity: int,
    order_id: str,
    idempotency_key: str,
    workflow_id: str,
) -> dict:
    """reserve_stock(product_id, quantity, order_id, idempotency_key, workflow_id): Reserves stock for an order."""
    return reserve_stock(product_id, quantity, order_id, idempotency_key, workflow_id)


@mcp.tool()
def mcp_create_reorder_proposal(
    product_id: int, quantity: int, workflow_id: str, reason: str
) -> dict:
    """create_reorder_proposal(product_id, quantity, workflow_id, reason): Creates reorder proposal."""
    return create_reorder_proposal(product_id, quantity, workflow_id, reason)


@mcp.tool()
def mcp_get_reorder_proposal(proposal_id: str) -> dict:
    """get_reorder_proposal(proposal_id): Returns one reorder proposal."""
    return get_reorder_proposal(proposal_id)


# Standards-compliant A2A server (Agent Framework + A2AExecutor)
agent = Agent(
    client=_build_chat_client(),
    name="Inventory Agent",
    instructions=(
        "You are an inventory operations agent. "
        "Input may be either raw JSON or text that includes one JSON object containing orderId, "
        "optional correlationId/workflowId, and items[]. "
        "Extract that JSON object and call process_order_inventory with it. "
        "You must call the process_order_inventory tool once. "
        "Return only the exact JSON string from the tool output. "
        "Do not add markdown or explanations."
    ),
    tools=[process_order_inventory],
    default_options={"tool_choice": "required"},
)


def _is_inventory_result_text(text: str) -> bool:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(payload, dict) and "orderId" in payload and "reservations" in payload
    )


class InventoryA2AExecutor(A2AExecutor):
    """
    Runs the LLM-driven path first and falls back to deterministic execution when
    the model does not perform tool calling (common with local non-tool models).
    """

    async def _run(self, query: Any, session: Any, updater: TaskUpdater) -> None:
        response = await self._agent.run(
            query, session=session, stream=False, **self._run_kwargs
        )
        response_messages = response.messages
        if not isinstance(response_messages, list):
            response_messages = [response_messages]

        last_text = ""
        for message in response_messages:
            for content in getattr(message, "contents", []):
                if getattr(content, "type", None) == "text" and getattr(
                    content, "text", None
                ):
                    last_text = content.text

        if _is_inventory_result_text(last_text):
            for message in response_messages:
                await self.handle_events(message, updater)
            return

        fallback_output = process_order_inventory(str(query))
        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=updater.new_agent_message(parts=[Part(text=fallback_output)]),
        )

    async def execute(self, context: Any, event_queue: Any) -> None:
        if context.context_id is None:
            raise ValueError("Context ID must be provided in the RequestContext")
        if context.message is None:
            raise ValueError("Message must be provided in the RequestContext")

        query = context.get_user_input()
        task = context.current_task
        if not task:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, context.context_id)
        await updater.submit()
        await updater.start_work()

        try:
            session = self._agent.create_session(session_id=task.context_id)
            if self._stream:
                await self._run_stream(query, session, updater)
            else:
                await self._run(query, session, updater)
        except Exception as llm_error:
            logger.warning(
                "LLM execution failed, using deterministic fallback: %s", llm_error
            )
            try:
                fallback_output = process_order_inventory(str(query))
                await updater.update_status(
                    state=TaskState.TASK_STATE_WORKING,
                    message=updater.new_agent_message(
                        parts=[Part(text=fallback_output)]
                    ),
                )
            except Exception as fallback_error:
                await updater.update_status(
                    state=TaskState.TASK_STATE_FAILED,
                    message=updater.new_agent_message(
                        parts=[Part(text=str(fallback_error))]
                    ),
                )
                return

        await updater.complete()


inventory_skill = AgentSkill(
    id="assess_order_inventory",
    name="Assess Order Inventory",
    description="Reserve inventory for order items and create reorder proposals when stock is low.",
    tags=["inventory", "reservation", "reorder"],
    examples=[
        '{"orderId":"order-123","correlationId":"corr-1","items":[{"productId":1,"quantity":2,"price":10.0}]}'
    ],
)

public_agent_card = AgentCard(
    name="Inventory Agent",
    description="Assesses inventory availability and creates reorder proposals.",
    version=APP_VERSION,
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=True),
    supported_interfaces=[
        AgentInterface(url=f"{PUBLIC_BASE_URL}/", protocol_binding="JSONRPC"),
    ],
    skills=[inventory_skill],
)

request_handler = DefaultRequestHandler(
    agent_executor=InventoryA2AExecutor(agent),
    task_store=InMemoryTaskStore(),
    agent_card=public_agent_card,
)


async def health(_: Any):
    return JSONResponse({"status": "ok", "version": APP_VERSION})


@contextlib.asynccontextmanager
async def lifespan(_: Starlette):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(mcp.session_manager.run())
        yield


app = Starlette(
    routes=[
        Route("/health", health),
        Mount("/mcp", mcp.streamable_http_app()),
        *create_agent_card_routes(public_agent_card),
        *create_jsonrpc_routes(request_handler, "/"),
    ],
    lifespan=lifespan,
)
