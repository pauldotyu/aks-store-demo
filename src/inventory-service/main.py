import os
import threading
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class InventoryRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: int = Field(alias="productId")
    available: int
    reserved: int
    reorder_threshold: int = Field(alias="reorderThreshold")
    reorder_quantity: int = Field(alias="reorderQuantity")
    version: int


class ReserveRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    order_id: str = Field(alias="orderId")
    quantity: int
    idempotency_key: str = Field(alias="idempotencyKey")
    workflow_id: str | None = Field(default=None, alias="workflowId")


class ReserveResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: int = Field(alias="productId")
    order_id: str = Field(alias="orderId")
    quantity: int
    available: int
    reserved: int
    proposal_id: str | None = Field(default=None, alias="proposalId")
    idempotency_key: str = Field(alias="idempotencyKey")


class ReorderProposalRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: int = Field(alias="productId")
    quantity: int
    workflow_id: str = Field(alias="workflowId")
    reason: str


class Proposal(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    proposal_id: str = Field(alias="proposalId")
    type: str
    product_id: int = Field(alias="productId")
    requested_quantity: int = Field(alias="requestedQuantity")
    current_available: int = Field(alias="currentAvailable")
    reorder_threshold: int = Field(alias="reorderThreshold")
    status: str
    reason: str
    workflow_id: str = Field(alias="workflowId")
    created_at: str = Field(alias="createdAt")
    approved_at: str | None = Field(default=None, alias="approvedAt")
    completed_at: str | None = Field(default=None, alias="completedAt")
    rejected_at: str | None = Field(default=None, alias="rejectedAt")


class ApproveRequest(BaseModel):
    approver: str | None = "demo-user"


class RejectRequest(BaseModel):
    reason: str = "Rejected by reviewer"


app = FastAPI(version=os.environ.get("APP_VERSION", "0.1.0"))
_lock = threading.Lock()
_inventory: dict[int, InventoryRecord] = {}
_proposals: dict[str, Proposal] = {}
_idempotency_results: dict[str, ReserveResponse] = {}
_active_proposal_index: dict[str, str] = {}


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _active_proposal_key(product_id: int, workflow_id: str) -> str:
    return f"{product_id}:{workflow_id}"


def _get_or_create_default_inventory(product_id: int) -> InventoryRecord:
    record = _inventory.get(product_id)
    if record:
        return record

    default_available = int(os.environ.get("INVENTORY_DEFAULT_AVAILABLE", "20"))
    default_threshold = int(os.environ.get("INVENTORY_DEFAULT_REORDER_THRESHOLD", "5"))
    default_quantity = int(os.environ.get("INVENTORY_DEFAULT_REORDER_QUANTITY", "25"))

    record = InventoryRecord(
        productId=product_id,
        available=default_available,
        reserved=0,
        reorderThreshold=default_threshold,
        reorderQuantity=default_quantity,
        version=1,
    )
    _inventory[product_id] = record
    return record


def _create_or_get_reorder_proposal(
    product_id: int,
    quantity: int,
    workflow_id: str,
    reason: str,
) -> Proposal:
    key = _active_proposal_key(product_id, workflow_id)
    existing_id = _active_proposal_index.get(key)
    if existing_id:
        return _proposals[existing_id]

    record = _inventory[product_id]
    proposal = Proposal(
        proposalId=str(uuid4()),
        type="inventory.reorder",
        productId=product_id,
        requestedQuantity=quantity,
        currentAvailable=record.available,
        reorderThreshold=record.reorder_threshold,
        status="pending",
        reason=reason,
        workflowId=workflow_id,
        createdAt=_utc_now_iso(),
    )
    _proposals[proposal.proposal_id] = proposal
    _active_proposal_index[key] = proposal.proposal_id
    return proposal


@app.on_event("startup")
def startup_seed_data() -> None:
    with _lock:
        seed_product_count = max(
            10, int(os.environ.get("INVENTORY_SEED_PRODUCT_COUNT", "10"))
        )
        seed_available = int(os.environ.get("INVENTORY_SEED_AVAILABLE", "100"))
        seed_threshold = int(os.environ.get("INVENTORY_SEED_REORDER_THRESHOLD", "50"))
        seed_quantity = int(os.environ.get("INVENTORY_SEED_REORDER_QUANTITY", "25"))
        for product_id in range(1, seed_product_count + 1):
            _inventory[product_id] = InventoryRecord(
                productId=product_id,
                available=seed_available,
                reserved=0,
                reorderThreshold=seed_threshold,
                reorderQuantity=seed_quantity,
                version=1,
            )


@app.get("/health")
def health():
    return {"status": "ok", "version": app.version}


@app.get("/inventory/{product_id}", response_model=InventoryRecord)
def get_inventory(product_id: int):
    with _lock:
        record = _get_or_create_default_inventory(product_id)
        return record


@app.post("/inventory/{product_id}/reserve", response_model=ReserveResponse)
def reserve_inventory(product_id: int, request: ReserveRequest):
    if request.quantity <= 0:
        raise HTTPException(
            status_code=400, detail="quantity must be a positive integer"
        )

    with _lock:
        existing = _idempotency_results.get(request.idempotency_key)
        if existing:
            return existing

        record = _get_or_create_default_inventory(product_id)
        if record.available < request.quantity:
            raise HTTPException(
                status_code=409,
                detail=f"insufficient stock for product {product_id}: available={record.available}, requested={request.quantity}",
            )

        record.available -= request.quantity
        record.reserved += request.quantity
        record.version += 1

        proposal_id = None
        workflow_id = request.workflow_id or request.order_id
        if record.available < record.reorder_threshold:
            reason = "Stock remaining after reservation is below threshold"
            proposal = _create_or_get_reorder_proposal(
                product_id=product_id,
                quantity=record.reorder_quantity,
                workflow_id=workflow_id,
                reason=reason,
            )
            proposal_id = proposal.proposal_id

        result = ReserveResponse(
            productId=product_id,
            orderId=request.order_id,
            quantity=request.quantity,
            available=record.available,
            reserved=record.reserved,
            proposalId=proposal_id,
            idempotencyKey=request.idempotency_key,
        )
        _idempotency_results[request.idempotency_key] = result
        return result


@app.get("/proposals")
def list_proposals():
    with _lock:
        return [_proposals[proposal_id] for proposal_id in sorted(_proposals)]


@app.get("/proposals/{proposal_id}", response_model=Proposal)
def get_proposal(proposal_id: str):
    with _lock:
        proposal = _proposals.get(proposal_id)
        if not proposal:
            raise HTTPException(status_code=404, detail="proposal not found")
        return proposal


@app.post("/proposals/reorder", response_model=Proposal)
def create_reorder_proposal(request: ReorderProposalRequest):
    if request.quantity <= 0:
        raise HTTPException(
            status_code=400, detail="quantity must be a positive integer"
        )

    with _lock:
        _get_or_create_default_inventory(request.product_id)
        proposal = _create_or_get_reorder_proposal(
            product_id=request.product_id,
            quantity=request.quantity,
            workflow_id=request.workflow_id,
            reason=request.reason,
        )
        return proposal


@app.post("/proposals/{proposal_id}/approve", response_model=Proposal)
def approve_proposal(proposal_id: str, request: ApproveRequest):
    with _lock:
        proposal = _proposals.get(proposal_id)
        if not proposal:
            raise HTTPException(status_code=404, detail="proposal not found")
        if proposal.status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"proposal cannot be approved from status {proposal.status}",
            )

        proposal.status = "approved"
        proposal.approved_at = _utc_now_iso()

        record = _get_or_create_default_inventory(proposal.product_id)
        record.available += proposal.requested_quantity
        record.version += 1

        proposal.status = "completed"
        proposal.completed_at = _utc_now_iso()
        _active_proposal_index.pop(
            _active_proposal_key(proposal.product_id, proposal.workflow_id), None
        )
        return proposal


@app.post("/proposals/{proposal_id}/reject", response_model=Proposal)
def reject_proposal(proposal_id: str, request: RejectRequest):
    with _lock:
        proposal = _proposals.get(proposal_id)
        if not proposal:
            raise HTTPException(status_code=404, detail="proposal not found")
        if proposal.status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"proposal cannot be rejected from status {proposal.status}",
            )

        proposal.status = "rejected"
        proposal.rejected_at = _utc_now_iso()
        proposal.reason = f"{proposal.reason}; rejection_reason={request.reason}"
        _active_proposal_index.pop(
            _active_proposal_key(proposal.product_id, proposal.workflow_id), None
        )
        return proposal
