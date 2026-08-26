"""Pydantic models shared by the generator, engine, metrics, and API layers."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Method(str, Enum):
    upi = "upi"
    card_domestic = "card_domestic"
    card_international = "card_international"
    netbanking = "netbanking"
    wallet = "wallet"


class EntityType(str, Enum):
    payment = "payment"
    refund = "refund"
    adjustment = "adjustment"


class ReasonCode(str, Enum):
    # matches / tags
    AUTO_MATCHED = "AUTO_MATCHED"
    ROUNDING_DRIFT_ABSORBED = "ROUNDING_DRIFT_ABSORBED"
    REFUND_IN_LATER_SETTLEMENT_OK = "REFUND_IN_LATER_SETTLEMENT_OK"
    MULTI_DAY_SETTLEMENT_OK = "MULTI_DAY_SETTLEMENT_OK"
    DUPLICATE_UTR_RESOLVED = "DUPLICATE_UTR_RESOLVED"
    FUZZY_NARRATION_MATCH = "FUZZY_NARRATION_MATCH"
    FEE_VARIANCE_INSTANT_OK = "FEE_VARIANCE_INSTANT_OK"
    # exceptions
    ORPHAN_ORDER = "ORPHAN_ORDER"
    PAYMENT_NO_ORDER = "PAYMENT_NO_ORDER"
    AMOUNT_MISMATCH_ORDER_PAYMENT = "AMOUNT_MISMATCH_ORDER_PAYMENT"
    FEE_MISMATCH = "FEE_MISMATCH"
    GST_MISMATCH = "GST_MISMATCH"
    UNLINKED_REFUND = "UNLINKED_REFUND"
    UNRECONCILED_ADJUSTMENT = "UNRECONCILED_ADJUSTMENT"
    SETTLEMENT_NET_MISMATCH = "SETTLEMENT_NET_MISMATCH"
    DUPLICATE_UTR_UNRESOLVED = "DUPLICATE_UTR_UNRESOLVED"
    MISSING_IN_BANK = "MISSING_IN_BANK"
    MISSING_IN_SETTLEMENT = "MISSING_IN_SETTLEMENT"
    TIMING_NOT_YET_SETTLED = "TIMING_NOT_YET_SETTLED"


class Order(BaseModel):
    order_id: str
    created_at: datetime
    gross_amount_paise: int
    currency: str = "INR"
    method: Method
    payment_id: Optional[str] = None
    customer_id: str
    status: Literal["captured", "failed", "pending"] = "captured"


class ReconTxn(BaseModel):
    """One row of razorpay_recon.csv -- a payment, refund, or adjustment."""

    settlement_id: str
    settlement_utr: str
    settled_at: datetime
    on_hold: bool = False
    is_instant: bool = False
    entity_type: EntityType
    entity_id: str
    parent_payment_id: Optional[str] = None
    order_id: Optional[str] = None
    method: Method
    captured_at: datetime
    gross_amount_paise: int = 0
    fee_paise: int = 0
    tax_paise: int = 0
    credit_paise: int = 0
    debit_paise: int = 0


class BankTxn(BaseModel):
    txn_date: datetime
    value_date: datetime
    utr: str
    narration: str
    credit_paise: int = 0
    debit_paise: int = 0
    balance_paise: int = 0
    bank_ref_no: str


class GroundTruthRow(BaseModel):
    entity_id: str
    # "order" | "payment" | "refund" | "adjustment" | "settlement" | "bank_credit"
    entity_type: str
    true_settlement_id: Optional[str] = None
    true_bank_utr: Optional[str] = None
    expected_net_paise: Optional[int] = None
    injected_anomaly: Optional[str] = None
    is_reconcilable: bool
    expected_reason_code: ReasonCode


class MatchRecord(BaseModel):
    stage: Literal["A", "B", "C"]
    entity_id: str
    reason_code: ReasonCode
    tags: list[ReasonCode] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class AIExplanation(BaseModel):
    explanation: str
    suggested_action: str
    model: str
    cached: bool = False


class Exception_(BaseModel):
    """Matches the `Exception object (pydantic)` shape in section 5.6. Named
    Exception_ to avoid shadowing the builtin; serialized as `exception_id` etc."""

    exception_id: str
    stage: Literal["A", "B", "C"]
    reason_code: ReasonCode
    entities: dict[str, Any]
    expected: dict[str, Any]
    actual: dict[str, Any]
    amount_impact_paise: int
    tolerance_applied_paise: int
    rule_trace: list[str]
    is_reconcilable: bool
    ai: Optional[AIExplanation] = None


class ReconResult(BaseModel):
    matches: list[MatchRecord]
    exceptions: list[Exception_]
    stage_counts: dict[str, int]
