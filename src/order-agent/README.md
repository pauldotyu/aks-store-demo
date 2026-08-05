# order-agent

Order Agent consumes the `agent-orders` queue, delegates inventory checks to `inventory-agent` through A2A, and can optionally run a Microsoft Agent Framework assessment using either a local model or a Foundry model.

## How it works

At startup, the FastAPI app launches a background consumer for RabbitMQ or Azure Service Bus. For each order message, it validates the event, sends the order items to `inventory-agent` through A2A, and optionally asks a configured OpenAI-compatible model to summarize the inventory outcome. Successful assessments are stored in the health state and written to stdout as structured JSON. The model assessment is advisory, so a model failure does not fail an otherwise valid order.

Successfully processed messages are acknowledged. Invalid JSON and malformed events are rejected or dead-lettered, while transient processing failures are requeued or abandoned for retry. `GET /health` reports the selected backend, connection state, processing counts, and the latest processing or model error.

## Prerequisites

- [Python 3](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/)
- RabbitMQ or Azure Service Bus
- `inventory-agent` running at `http://127.0.0.1:7002`

## Model provider options

Set `ORDER_AGENT_MODEL_PROVIDER` to one of:

- `none` (default): no model invocation
- `local`: uses `OPENAI_BASE_URL`, `OPENAI_CHAT_MODEL`, `OPENAI_API_KEY`
- `foundry`: uses `FOUNDRY_OPENAI_BASE_URL`, `FOUNDRY_OPENAI_CHAT_MODEL`, `FOUNDRY_OPENAI_API_KEY`

The agent uses `OpenAIChatClient` from Microsoft Agent Framework, so both providers must expose an OpenAI-compatible endpoint.

For passwordless Foundry access, set `USE_WORKLOAD_IDENTITY_AUTH=true` with
`AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_CHAT_MODEL`, and `AZURE_OPENAI_API_VERSION`.
The workload identity requires the `Cognitive Services OpenAI User` role on the
Foundry resource. `FOUNDRY_OPENAI_API_KEY` is not required on this path.

## Environment variables

Copy `.env.example` and set values for your environment.

The queue backend is selected automatically. A hostname ending in
`.servicebus.windows.net` or `USE_WORKLOAD_IDENTITY_AUTH=true` selects Azure Service Bus;
all other hostnames select RabbitMQ.

For Service Bus with Microsoft Entra workload identity:

```bash
export ORDER_QUEUE_HOSTNAME=<namespace>.servicebus.windows.net
export ORDER_QUEUE_NAME=agent-orders
export USE_WORKLOAD_IDENTITY_AUTH=true
unset ORDER_QUEUE_USERNAME ORDER_QUEUE_PASSWORD
```

The identity requires the `Azure Service Bus Data Receiver` role on the namespace or queue.
For Service Bus SAS authentication, set `ORDER_QUEUE_USERNAME` to the shared access policy name
and `ORDER_QUEUE_PASSWORD` to its key instead of enabling workload identity.

## Running the app locally

Open a terminal in `src/order-agent` and run:

```bash
uv sync

export ORDER_QUEUE_NAME=agent-orders
export ORDER_QUEUE_HOSTNAME=127.0.0.1
export ORDER_QUEUE_PORT=5672
export ORDER_QUEUE_USERNAME=username
export ORDER_QUEUE_PASSWORD=password
export INVENTORY_AGENT_A2A_URL=http://127.0.0.1:7002

# choose one: none, local, foundry
export ORDER_AGENT_MODEL_PROVIDER=none

# local provider values (used when ORDER_AGENT_MODEL_PROVIDER=local)
export OPENAI_BASE_URL=http://127.0.0.1:11434/v1
export OPENAI_CHAT_MODEL=gpt-oss:20b
export OPENAI_API_KEY=none

# foundry provider values (used when ORDER_AGENT_MODEL_PROVIDER=foundry)
export FOUNDRY_OPENAI_BASE_URL=
export FOUNDRY_OPENAI_CHAT_MODEL=
export FOUNDRY_OPENAI_API_KEY=

# foundry workload identity values (used when ORDER_AGENT_MODEL_PROVIDER=foundry)
export USE_WORKLOAD_IDENTITY_AUTH=false
export AZURE_OPENAI_ENDPOINT=
export AZURE_OPENAI_CHAT_MODEL=
export AZURE_OPENAI_API_VERSION=2024-12-01-preview

uv run uvicorn main:app --host 127.0.0.1 --port 7003
```

## Running with Docker Compose

The `docker-compose.yml` in this directory starts the full agent stack: `rabbitmq`, `inventory-service`, `inventory-agent`, and `order-agent`.

```bash
# Start without telemetry
docker compose up --build

# Start with the LGTM telemetry stack (Grafana at http://localhost:3000)
ENABLE_INSTRUMENTATION=true docker compose --profile telemetry up --build

# Stop all services (including telemetry stack)
docker compose --profile telemetry down
```

> **Note:** On Linux, Ollama must bind to all interfaces (`OLLAMA_HOST=0.0.0.0 ollama serve`) so the
> container can reach it via `host.docker.internal`.

## Manual testing

`order-agent` is a queue consumer with no A2A or MCP endpoints. Testing means publishing a message to RabbitMQ or Azure Service Bus and verifying the agent processes it.

### 1. Health check

The health endpoint includes rich consumer state:

```bash
curl -s http://localhost:7003/health | jq
```

Look for `"connected": true` and the expected `"queueBackend"`. If `connected` is `false`, the consumer is still connecting to the queue; wait a few seconds and retry.

### 2. Publish a test message via RabbitMQ management API

The RabbitMQ management UI is at **<http://localhost:15672>** (credentials: `username` / `password`).

Or publish directly via the REST API:

```bash
curl -s -u username:password http://localhost:15672/api/exchanges/%2F/amq.default/publish \
  -H "Content-Type: application/json" \
  -d '{
    "properties": {},
    "routing_key": "agent-orders",
    "payload": "{\"orderId\":\"order-test-1\",\"correlationId\":\"corr-1\",\"eventId\":\"evt-1\",\"eventType\":\"order.created\",\"eventVersion\":\"1.0\",\"customerId\":\"customer-1\",\"createdAt\":\"2026-08-03T00:00:00Z\",\"items\":[{\"productId\":1,\"quantity\":2,\"price\":10.0}]}",
    "payload_encoding": "string"
  }' | jq
```

Required message fields: `orderId`, `correlationId`, `eventId`, `eventType`, `eventVersion`, `customerId`, `items` (non-empty array).

### 3. Verify the message was processed

```bash
curl -s http://localhost:7003/health | jq '.consumer.processed, .consumer.lastProcessedAt, .consumer.lastError'
```

`processed` should increment by 1 and `lastError` should be `null`.

### 4. Publish via Python (alternative)

Useful when running the agent locally without Docker:

```bash
uv run python - <<'PY'
import json, pika
payload = {
  "eventId": "evt-1", "correlationId": "corr-1",
  "eventType": "order.created", "eventVersion": "1.0",
  "createdAt": "2026-01-01T00:00:00Z",
  "orderId": "order-1", "customerId": "cust-1",
  "items": [{"productId": 1, "quantity": 2, "price": 10.0}]
}
conn = pika.BlockingConnection(
  pika.ConnectionParameters(host="127.0.0.1", port=5672,
    credentials=pika.PlainCredentials("username", "password")))
ch = conn.channel()
ch.queue_declare(queue="agent-orders", durable=True)
ch.basic_publish(exchange="", routing_key="agent-orders", body=json.dumps(payload))
conn.close()
print("published")
PY
```

### 5. Telemetry (when running with the telemetry profile)

Open Grafana at **<http://localhost:3000>** (no login required). Allow 15-30 seconds after sending requests for data to appear.

**Viewing traces in Tempo:**

1. Click **Explore** (compass icon in the left sidebar)
2. Select **Tempo** from the datasource dropdown
3. Set query type to **Search**
4. Set **Service Name** to `order-agent`
5. Click **Run query** to list recent traces
6. Click any trace to open the span waterfall view
7. Click the log icon on a span to jump to correlated Loki logs

**Querying logs in Loki:**

1. Click **Explore** and select **Loki**
2. Use the query: `{service_name="order-agent"}`
3. Set the time range to **Last 15 minutes** and click **Run query**

**Querying metrics in Prometheus:**

1. Click **Explore** and select **Prometheus**
2. Query `gen_ai_client_token_usage_bucket` for LLM token usage
3. Query `http_server_request_duration_seconds_bucket` for request latency

> **No data?** The most common cause is `ENABLE_INSTRUMENTATION` not being set. Confirm with
> `docker compose exec order-agent env | grep ENABLE` -- it must show `ENABLE_INSTRUMENTATION=true`.
> Also confirm the time range in Grafana is set to **Last 15 minutes** or shorter.

## Health endpoint

`GET /health` returns queue consumer status and the latest model-provider outcome metadata.
