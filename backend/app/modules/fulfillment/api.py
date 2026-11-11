from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from ...common import Key, VersionInput, fail, iso, now
from ...database import get_db
from ..identity.dependencies import current_identity
from ..orders.gateway import OrderGateway
from . import service
from .contract import CancelInput, ReviewInput, StatusInput
from .credit import CreditService
from .models import Notification, Review, ReviewOpening

router = APIRouter(prefix="/api", tags=["fulfillment"])


def response(value):
    return JSONResponse(value["body"], status_code=value["statusCode"])


@router.post("/orders/{order_id}/accept")
def accept(order_id: str, body: VersionInput, idempotency_key: Key,
           user=Depends(current_identity), db: Session = Depends(get_db)):
    return response(service.execute(db, user, order_id, "accept", body, idempotency_key))


@router.post("/orders/{order_id}/status")
def advance(order_id: str, body: StatusInput, idempotency_key: Key,
            user=Depends(current_identity), db: Session = Depends(get_db)):
    return response(service.execute(db, user, order_id, "status", body, idempotency_key))


@router.post("/orders/{order_id}/cancel")
def cancel(order_id: str, body: CancelInput, idempotency_key: Key,
           user=Depends(current_identity), db: Session = Depends(get_db)):
    return response(service.execute(db, user, order_id, "cancel", body, idempotency_key))


@router.get("/orders/{order_id}/status")
def status(order_id: str, user=Depends(current_identity), db: Session = Depends(get_db)):
    order = OrderGateway.related(db, order_id, user.uid)
    return {"orderId": order.id, "status": order.status, "paymentStatus": order.payment_status,
            "refundStatus": order.refund_status, "version": order.version}


def pagination(request):
    if set(request.query_params) - {"page", "pageSize"}:
        fail(422, "VALIDATION_ERROR", "查询包含未声明字段")
    for field in ("page", "pageSize"):
        value = request.query_params.get(field)
        if value is not None and (not value.isascii() or not value.isdigit()):
            fail(422, "VALIDATION_ERROR", "分页参数必须为正整数", {field: "请输入正整数"})


def paged(db, model, conditions, page, page_size, render):
    total = db.scalar(select(func.count()).select_from(model).where(*conditions))
    rows = db.scalars(select(model).where(*conditions).order_by(model.created_at.desc(), model.id.desc())
                      .offset((page - 1) * page_size).limit(page_size))
    return {"items": [render(row) for row in rows], "total": total, "page": page, "pageSize": page_size}


@router.get("/orders/{order_id}/notifications")
def notifications(order_id: str, request: Request, page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100),
                  user=Depends(current_identity), db: Session = Depends(get_db)):
    pagination(request)
    OrderGateway.related(db, order_id, user.uid)
    return paged(db, Notification, [Notification.order_id == order_id, Notification.uid == user.uid], page, pageSize,
        lambda row: {"notificationId": row.id, "orderId": row.order_id, "type": row.type,
                     "message": row.message, "createdAt": row.created_at})


@router.get("/users/{uid}/credit")
def credit(uid: str, user=Depends(current_identity), db: Session = Depends(get_db)):
    if uid != user.uid:
        fail(404, "NOT_FOUND", "信用记录不存在或不可访问")
    return CreditService.get(db, uid)


@router.post("/orders/{order_id}/reviews", status_code=201)
def review(order_id: str, body: ReviewInput, user=Depends(current_identity), db: Session = Depends(get_db)):
    order = OrderGateway.related(db, order_id, user.uid)
    if order.status != "completed" or not db.get(ReviewOpening, order_id):
        fail(409, "ORDER_CONFLICT", "订单尚未确认收货或评价入口准备中，请稍后刷新")
    publisher = user.uid == order.publisher_uid
    target = order.courier_uid if publisher else order.publisher_uid
    if not target or target == user.uid:
        fail(403, "FORBIDDEN", "不能评价自己")
    review_id, created = str(uuid4()), iso(now())
    changed = db.execute(insert(Review).values(id=review_id, order_id=order.id, reviewer_uid=user.uid,
        reviewee_uid=target, reviewer_role="publisher" if publisher else "courier", rating=body.rating,
        tags=body.tags, comment=body.comment, created_at=created).on_conflict_do_nothing(
            index_elements=[Review.order_id, Review.reviewer_uid]))
    if changed.rowcount != 1:
        fail(409, "ALREADY_REVIEWED", "此订单已评价，提交后不可修改")
    db.commit()
    return {"reviewId": review_id, "orderId": order.id, "createdAt": created}


@router.get("/orders/{order_id}/reviews")
def reviews(order_id: str, request: Request, page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100),
            user=Depends(current_identity), db: Session = Depends(get_db)):
    pagination(request)
    order = OrderGateway.related(db, order_id, user.uid)
    result = paged(db, Review, [Review.order_id == order_id], page, pageSize,
        lambda row: {"reviewId": row.id, "orderId": row.order_id, "reviewerUid": row.reviewer_uid,
                     "revieweeUid": row.reviewee_uid, "reviewerRole": row.reviewer_role,
                     "rating": row.rating, "tags": row.tags, "comment": row.comment, "createdAt": row.created_at})
    result["reviewable"] = order.status == "completed" and db.get(ReviewOpening, order_id) is not None
    return result
