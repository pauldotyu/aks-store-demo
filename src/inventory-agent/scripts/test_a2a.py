import argparse
import asyncio
import json
from urllib.parse import urlparse

import httpx
from a2a.client import A2ACardResolver
from agent_framework.a2a import A2AAgent


def _normalize_card_urls(card, base_url: str):
    """
    For local testing, force agent-card interface URLs to the provided base URL.
    This avoids DNS issues when the server advertises an in-cluster hostname.
    """
    parsed = urlparse(base_url)
    normalized_base = f"{parsed.scheme}://{parsed.netloc}/"

    if not getattr(card, "supported_interfaces", None):
        return

    for interface in card.supported_interfaces:
        interface.url = normalized_base


async def run(base_url: str, product_id: int, quantity: int):
    async with httpx.AsyncClient(timeout=60.0) as http_client:
        card = await A2ACardResolver(httpx_client=http_client, base_url=base_url).get_agent_card()
        _normalize_card_urls(card, base_url)
        print(f"agent: {card.name}")
        print(f"skills: {[s.name for s in card.skills]}")

    payload = {
        "orderId": "order-a2a-test-1",
        "correlationId": "corr-a2a-test-1",
        "workflowId": "order-a2a-test-1",
        "items": [{"productId": product_id, "quantity": quantity, "price": 10.0}],
    }
    prompt = (
        "Process this order inventory request and return only the tool output JSON:\n"
        f"{json.dumps(payload)}"
    )

    async with A2AAgent(name=card.name, agent_card=card, url=base_url) as agent:
        response = await agent.run(prompt)
        if not response.messages:
            raise RuntimeError("A2A response contained no messages")
        print(response.messages[-1].text)


def main():
    parser = argparse.ArgumentParser(description="Smoke test for inventory-agent A2A endpoint")
    parser.add_argument("--base-url", default="http://127.0.0.1:7002", help="Base URL for inventory-agent")
    parser.add_argument("--product-id", type=int, default=1, help="Product ID to reserve")
    parser.add_argument("--quantity", type=int, default=2, help="Quantity to reserve")
    args = parser.parse_args()

    asyncio.run(run(args.base_url, args.product_id, args.quantity))


if __name__ == "__main__":
    main()
