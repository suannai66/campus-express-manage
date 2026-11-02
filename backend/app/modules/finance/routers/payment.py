"""余额支付冻结与本人支付结果查询。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ....common import Key
from ....database import get_db
from ...identity.dependencies import current_identity
from ..schemas import PrepayRequest, PrepayResponse
from ..services import payment

router = APIRouter(prefix="/api/pay", tags=["finance: F7 支付"])


@router.post("/prepay", response_model=PrepayResponse)
def prepay(
    request: PrepayRequest,
    idempotency_key: Key,
    db: Session = Depends(get_db),
    user=Depends(current_identity),
):
    return payment.prepay(db, user.uid, request, idempotency_key)


@router.get("/payments/{payment_id}", response_model=PrepayResponse)
def payment_query(payment_id: str, db: Session = Depends(get_db), user=Depends(current_identity)):
    return payment.query_payment(db, user.uid, payment_id)
