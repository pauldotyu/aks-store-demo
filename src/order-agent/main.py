import asyncio
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import pika
from a2a.client import A2ACardResolver
from agent_framework import Agent
from agent_framework.a2a import A2AAgent
from agent_framework.observability import configure_otel_providers
from agent_framework.openai import OpenAIChatClient
from azure.core.credentials import AzureNamedKeyCredential
from azure.identity import DefaultAzureCredential
from azure.servicebus import AutoLockRenewer, ServiceBusClient
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


ENABLE_INSTRUMENTATION = _env_bool("ENABLE_INSTRUMENTATION", False)
if ENABLE_INSTRUMENTATION:
    configure_otel_providers(enable_sensitive_data=False)


class ConsumerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.connected = False
        self.processed = 0
        self.failed = 0
        self.last_error = None
        self.last_processed_at = None
        self.last_model_provider = None
        self.last_model_result = None
        self.last_model_error = None

    def set_connected(self, connected: bool):
        with self.lock:
            self.connected = connected

    def record_success(self):
        with self.lock:
            self.processed += 1
            self.last_processed_at = datetime.now(timezone.utc).isoformat()
            self.last_error = None

    def record_failure(self, err: str):
        with self.lock:
            self.failed += 1
            self.last_error = err
            self.last_processed_at = datetime.now(timezone.utc).isoformat()

    def record_model_result(self, provider: str, result: dict[str, Any]):
        with self.lock:
            self.last_model_provider = provider
            self.last_model_result = result
            self.last_model_error = None

    def record_model_error(self, provider: str, err: str):
        with self.lock:
            self.last_model_provider = provider
            self.last_model_error = err

    def snapshot(self):
        with self.lock:
            return {
                "startedAt": self.started_at,
                "connected": self.connected,
                "processed": self.processed,
                "failed": self.failed,
                "lastError": self.last_error,
                "lastProcessedAt": self.last_processed_at,
                "lastModelProvider": self.last_model_provider,
                "lastModelResult": self.last_model_result,
                "lastModelError": self.last_model_error,
            }


APP_VERSION = os.environ.get("APP_VERSION", "0.1.0")
INVENTORY_AGENT_A2A_URL = os.environ.get(
    "INVENTORY_AGENT_A2A_URL", "http://inventory-agent:7002"
).rstrip("/")
INVENTORY_TIMEOUT_SECONDS = float(
    os.environ.get("INVENTORY_AGENT_TIMEOUT_SECONDS", "60")
)
QUEUE_NAME = os.environ.get("ORDER_QUEUE_NAME", "agent-orders")
QUEUE_HOST = os.environ.get("ORDER_QUEUE_HOSTNAME", "rabbitmq")
QUEUE_PORT = int(os.environ.get("ORDER_QUEUE_PORT", "5672"))
QUEUE_USERNAME = os.environ.get("ORDER_QUEUE_USERNAME", "username")
QUEUE_PASSWORD = os.environ.get("ORDER_QUEUE_PASSWORD", "password")
QUEUE_URI = os.environ.get("ORDER_QUEUE_URI")
USE_WORKLOAD_IDENTITY_AUTH = _env_bool("USE_WORKLOAD_IDENTITY_AUTH", False)
SERVICE_BUS_NAMESPACE = os.environ.get(
    "AZURE_SERVICEBUS_FULLYQUALIFIEDNAMESPACE", QUEUE_HOST
)
QUEUE_BACKEND = (
    "servicebus"
    if SERVICE_BUS_NAMESPACE.endswith(".servicebus.windows.net")
    or USE_WORKLOAD_IDENTITY_AUTH
    else "rabbitmq"
)
MODEL_PROVIDER = os.environ.get("ORDER_AGENT_MODEL_PROVIDER", "none").strip().lower()

state = ConsumerState()
app = FastAPI(version=APP_VERSION)


def _build_connection_parameters() -> pika.ConnectionParameters:
    if QUEUE_URI:
        return pika.URLParameters(QUEUE_URI)
    credentials = pika.PlainCredentials(QUEUE_USERNAME, QUEUE_PASSWORD)
    return pika.ConnectionParameters(
        host=QUEUE_HOST, port=QUEUE_PORT, credentials=credentials
    )


async def _call_inventory_agent_async(order_event: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "orderId": order_event["orderId"],
        "correlationId": order_event.get("correlationId"),
        "workflowId": order_event.get("orderId"),
        "items": order_event["items"],
    }
    payload_text = json.dumps(payload)

    async with httpx.AsyncClient(timeout=INVENTORY_TIMEOUT_SECONDS) as http_client:
        resolver = A2ACardResolver(
            httpx_client=http_client, base_url=INVENTORY_AGENT_A2A_URL
        )
        agent_card = await resolver.get_agent_card()

    async with A2AAgent(
        name=agent_card.name,
        agent_card=agent_card,
        url=INVENTORY_AGENT_A2A_URL,
    ) as agent:
        response = await agent.run(payload_text)
        message_texts = [m.text for m in response.messages if getattr(m, "text", None)]
        if not message_texts:
            raise RuntimeError(
                "inventory-agent A2A response did not contain text output"
            )
        return json.loads(message_texts[-1])


def _call_inventory_agent(order_event: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_call_inventory_agent_async(order_event))


def _validate_event(event: dict[str, Any]):
    required = [
        "orderId",
        "customerId",
        "items",
        "eventId",
        "correlationId",
        "eventType",
        "eventVersion",
    ]
    missing = [key for key in required if key not in event]
    if missing:
        raise ValueError(f"missing required event fields: {','.join(missing)}")
    if not isinstance(event["items"], list) or len(event["items"]) == 0:
        raise ValueError("items must be a non-empty array")


def _provider_env(provider: str) -> dict[str, str]:
    if provider == "local":
        return {
            "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL", ""),
            "OPENAI_CHAT_MODEL": os.environ.get("OPENAI_CHAT_MODEL", ""),
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
        }
    if provider == "foundry":
        # Map Foundry-specific settings onto the OpenAIChatClient env names.
        return {
            "OPENAI_BASE_URL": os.environ.get("FOUNDRY_OPENAI_BASE_URL", ""),
            "OPENAI_CHAT_MODEL": os.environ.get("FOUNDRY_OPENAI_CHAT_MODEL", ""),
            "OPENAI_API_KEY": os.environ.get("FOUNDRY_OPENAI_API_KEY", ""),
        }
    raise ValueError(f"unsupported ORDER_AGENT_MODEL_PROVIDER: {provider}")


def _validate_provider_env(provider: str) -> dict[str, str]:
    values = _provider_env(provider)
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise ValueError(
            f"{provider} provider missing required env vars: {','.join(missing)}"
        )
    return values


def _build_assessment_chat_client(provider: str) -> OpenAIChatClient:
    if provider != "foundry" or not USE_WORKLOAD_IDENTITY_AUTH:
        return OpenAIChatClient()

    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    model = os.environ.get("AZURE_OPENAI_CHAT_MODEL") or os.environ.get(
        "FOUNDRY_OPENAI_CHAT_MODEL"
    )
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION")
    if not azure_endpoint:
        raise RuntimeError(
            "Foundry workload identity auth requires AZURE_OPENAI_ENDPOINT"
        )
    if not model:
        raise RuntimeError(
            "Foundry workload identity auth requires AZURE_OPENAI_CHAT_MODEL "
            "or FOUNDRY_OPENAI_CHAT_MODEL"
        )
    if not api_version:
        raise RuntimeError(
            "Foundry workload identity auth requires AZURE_OPENAI_API_VERSION"
        )

    return OpenAIChatClient(
        model=model,
        azure_endpoint=azure_endpoint,
        api_version=api_version,
        credential=DefaultAzureCredential(),
    )


async def _run_assessment_agent_async(
    provider: str, order_event: dict[str, Any], inventory_result: dict[str, Any]
) -> dict[str, Any]:
    use_passwordless = provider == "foundry" and USE_WORKLOAD_IDENTITY_AUTH
    values = {} if use_passwordless else _validate_provider_env(provider)
    previous = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        instructions = (
            "You are the Order Agent in an e-commerce workflow. "
            "Return only JSON with fields: "
            "action, requiresReorderApproval, proposalIds, summary. "
            "action must be one of: reserved_ok, reserved_with_reorder, failed. "
            "summary must be <= 120 chars."
        )
        prompt = {
            "orderEvent": order_event,
            "inventoryAssessment": inventory_result,
        }
        async with Agent(
            client=_build_assessment_chat_client(provider),
            name="OrderAgent",
            instructions=instructions,
        ) as agent:
            result = await agent.run(json.dumps(prompt))
        text = (result.text or "").strip()
        parsed = json.loads(text)
        return {
            "action": parsed.get("action", "reserved_ok"),
            "requiresReorderApproval": bool(
                parsed.get("requiresReorderApproval", False)
            ),
            "proposalIds": parsed.get("proposalIds", []),
            "summary": parsed.get("summary", ""),
        }
    finally:
        for key, original_value in previous.items():
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value


def _run_assessment_agent(
    order_event: dict[str, Any], inventory_result: dict[str, Any]
) -> dict[str, Any] | None:
    if MODEL_PROVIDER == "none":
        return None
    return asyncio.run(
        _run_assessment_agent_async(MODEL_PROVIDER, order_event, inventory_result)
    )


def _process_message(body: bytes):
    event = json.loads(body.decode("utf-8"))
    _validate_event(event)
    inventory_result = _call_inventory_agent(event)

    try:
        model_result = _run_assessment_agent(event, inventory_result)
        if model_result is not None:
            state.record_model_result(MODEL_PROVIDER, model_result)
            print(
                json.dumps(
                    {
                        "event": "order_agent.advisory_assessment",
                        "orderId": event["orderId"],
                        "provider": MODEL_PROVIDER,
                        "assessment": model_result,
                    }
                ),
                flush=True,
            )
    except Exception as model_err:
        # Model assessment is advisory, do not fail order processing path.
        state.record_model_error(MODEL_PROVIDER, str(model_err))

    state.record_success()


def _handle_rabbit_message(ch, method, properties, body):
    try:
        _process_message(body)

        ch.basic_ack(delivery_tag=method.delivery_tag)
    except (json.JSONDecodeError, ValueError) as err:
        # Permanent failure: malformed JSON or schema validation error. Dead-letter
        # the message rather than requeueing to avoid an infinite retry loop.
        state.record_failure(str(err))
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    except Exception as err:
        state.record_failure(str(err))
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


def _consume_rabbitmq_forever():
    while True:
        connection = None
        try:
            params = _build_connection_parameters()
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.basic_qos(prefetch_count=1)
            state.set_connected(True)
            channel.basic_consume(
                queue=QUEUE_NAME,
                on_message_callback=_handle_rabbit_message,
                auto_ack=False,
            )
            channel.start_consuming()
        except Exception as err:
            state.set_connected(False)
            state.record_failure(f"consumer loop error: {err}")
            time.sleep(5)
        finally:
            state.set_connected(False)
            if connection and connection.is_open:
                connection.close()


def _service_bus_credential():
    if USE_WORKLOAD_IDENTITY_AUTH:
        return DefaultAzureCredential()
    if QUEUE_USERNAME and QUEUE_PASSWORD:
        return AzureNamedKeyCredential(QUEUE_USERNAME, QUEUE_PASSWORD)
    return DefaultAzureCredential()


def _service_bus_message_body(message) -> bytes:
    return b"".join(message.body)


def _consume_service_bus_forever():
    while True:
        try:
            credential = _service_bus_credential()
            with (
                ServiceBusClient(SERVICE_BUS_NAMESPACE, credential) as client,
                client.get_queue_receiver(
                    queue_name=QUEUE_NAME, prefetch_count=1
                ) as receiver,
                AutoLockRenewer(max_lock_renewal_duration=300) as lock_renewer,
            ):
                state.set_connected(True)
                while True:
                    messages = receiver.receive_messages(
                        max_message_count=1, max_wait_time=5
                    )
                    for message in messages:
                        lock_renewer.register(receiver, message)
                        try:
                            _process_message(_service_bus_message_body(message))
                            receiver.complete_message(message)
                        except (json.JSONDecodeError, ValueError) as err:
                            state.record_failure(str(err))
                            receiver.dead_letter_message(
                                message,
                                reason="InvalidOrderEvent",
                                error_description=str(err),
                            )
                        except Exception as err:
                            state.record_failure(str(err))
                            receiver.abandon_message(message)
        except Exception as err:
            state.set_connected(False)
            state.record_failure(f"consumer loop error: {err}")
            time.sleep(5)
        finally:
            state.set_connected(False)


def _consume_forever():
    if QUEUE_BACKEND == "servicebus":
        _consume_service_bus_forever()
    else:
        _consume_rabbitmq_forever()


@app.on_event("startup")
def startup_consumer():
    consumer = threading.Thread(target=_consume_forever, daemon=True)
    consumer.start()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "consumer": state.snapshot(),
        "queueBackend": QUEUE_BACKEND,
        "modelProvider": MODEL_PROVIDER,
    }
