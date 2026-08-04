# inventory-service

This is a FastAPI app that provides deterministic inventory and reorder proposal APIs for the optional agents feature.

It owns:

- Inventory records (available, reserved, thresholds, reorder quantity)
- Inventory reservation with idempotency keys
- Reorder proposal creation
- Proposal approval and rejection

## Prerequisites

- [Python 3](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/)

## Running the app locally

Open a terminal in `src/inventory-service` and run:

```bash
uv sync

export INVENTORY_SEED_PRODUCT_COUNT=10
export INVENTORY_SEED_AVAILABLE=100
export INVENTORY_SEED_REORDER_THRESHOLD=50
export INVENTORY_SEED_REORDER_QUANTITY=25

uv run uvicorn main:app --host 127.0.0.1 --port 7001
```

The service seeds inventory for product IDs 1 through 10, matching the initial products in `product-service/src/models.rs`.

## Testing this service individually

With the service running on port 7001:

```bash
# health
curl -s http://127.0.0.1:7001/health

# read inventory
curl -s http://127.0.0.1:7001/inventory/1

# reserve inventory
curl -s -X POST http://127.0.0.1:7001/inventory/1/reserve \
  -H 'content-type: application/json' \
  -d '{
    "orderId":"order-1",
    "quantity":2,
    "idempotencyKey":"order-1:1:2",
    "workflowId":"order-1"
  }'

# list proposals
curl -s http://127.0.0.1:7001/proposals
```

Use the [`test-inventory-service.http`](./test-inventory-service.http) file with the VS Code REST Client extension for manual endpoint testing.
