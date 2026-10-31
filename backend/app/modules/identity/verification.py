"""F2 编排：申请、当前状态、审核审计与通知在同一请求事务保存。"""
from io import BytesIO
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert

from ...common import fail, iso, now
from .models import (VerificationApplication as Application, VerificationState as State,
                     VerificationPhoto as Photo, VerificationReview as Review,
                     VerificationNotification as Notification)

MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_PHOTO_PIXELS = 25_000_000


def photo_type(content):
    if not content or len(content) > MAX_PHOTO_BYTES:
        fail(422, "VALIDATION_ERROR", "请选择不超过 5 MB 的 JPEG / PNG 照片", {"photo": "照片为空或超过 5 MB"})
    try:
        with Image.open(BytesIO(content), formats=["JPEG", "PNG"]) as image:
            if image.width * image.height > MAX_PHOTO_PIXELS:
                raise ValueError("图片像素过大")
            kind = image.format
            image.verify()
        with Image.open(BytesIO(content), formats=["JPEG", "PNG"]) as image:
            image.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError):
        fail(422, "VALIDATION_ERROR", "照片内容无效、损坏或像素过大", {"photo": "请重新选择 JPEG / PNG 照片（不超过 2500 万像素）"})
    return "image/jpeg" if kind == "JPEG" else "image/png"


def submit_application(db, uid, real_name, student_no, content):
    kind = photo_type(content)
    application_id = str(uuid4())
    state = dict(uid=uid, status="pending", reject_reason=None, application_id=application_id, version=1)
    # 首次申请和驳回重提同样走条件写入，并发提交只有一份成功。
    changed = db.execute(insert(State).values(**state).on_conflict_do_update(
        index_elements=[State.uid], set_=state, where=State.status == "rejected"))
    if changed.rowcount != 1:
        fail(409, "VERIFICATION_CONFLICT", "已有待审核申请或认证已通过，请刷新状态")
    db.add(Application(application_id=application_id, uid=uid, real_name=real_name,
                       student_no=student_no, status="pending", version=1, created_at=iso(now())))
    db.add(Photo(application_id=application_id, content_type=kind, content=content))
    db.commit()
    return {"applicationId": application_id, "status": "pending", "version": 1}


def require_admin(user):
    if user.role != "admin":
        fail(403, "FORBIDDEN", "仅管理员可审核认证申请")


def find_application(db, application_id):
    row = db.get(Application, application_id)
    if not row:
        fail(404, "NOT_FOUND", "认证申请不存在或不可访问")
    return row


def application_view(row, full=False):
    masked = "*" * len(row.student_no) if len(row.student_no) <= 4 else "*" * (len(row.student_no) - 4) + row.student_no[-4:]
    result = {"applicationId": row.application_id, "realName": row.real_name,
              "studentNo": row.student_no if full else masked, "status": row.status,
              "version": row.version, "rejectReason": row.reject_reason,
              "createdAt": row.created_at, "reviewedAt": row.reviewed_at}
    if full:
        result.update(uid=row.uid, reviewerUid=row.reviewer_uid)
    return result


def application_page(db, page, page_size, uid=None, status=None):
    conditions = []
    if uid is not None: conditions.append(Application.uid == uid)
    if status is not None: conditions.append(Application.status == status)
    total = db.scalar(select(func.count()).select_from(Application).where(*conditions))
    rows = db.scalars(select(Application).where(*conditions).order_by(
        Application.created_at.desc(), Application.application_id.desc()).offset((page - 1) * page_size).limit(page_size))
    return {"items": [application_view(row) for row in rows], "total": total, "page": page, "pageSize": page_size}


def review_application(db, application_id, admin_uid, decision, reason, version):
    application = find_application(db, application_id)
    reviewed_at = iso(now())
    changed = db.execute(update(Application).where(Application.application_id == application_id,
        Application.status == "pending", Application.version == version).values(
        status=decision, reject_reason=reason, version=Application.version + 1,
        reviewed_at=reviewed_at, reviewer_uid=admin_uid))
    if changed.rowcount != 1:
        fail(409, "VERIFICATION_CONFLICT", "申请已审核或版本已变化，请刷新后重试")
    changed = db.execute(update(State).where(State.uid == application.uid,
        State.application_id == application_id, State.status == "pending", State.version == version).values(
        status=decision, reject_reason=reason, version=State.version + 1))
    if changed.rowcount != 1:
        fail(409, "VERIFICATION_CONFLICT", "当前认证申请已变化，请刷新后重试")
    db.add(Review(review_id=str(uuid4()), application_id=application_id, reviewer_uid=admin_uid,
                  decision=decision, reject_reason=reason, version=version + 1, created_at=reviewed_at))
    db.add(Notification(notification_id=str(uuid4()), application_id=application_id, uid=application.uid,
                        status=decision, reject_reason=reason, version=version + 1, created_at=reviewed_at))
    db.commit()
    return {"applicationId": application_id, "status": decision, "version": version + 1}


def notification_page(db, uid, page, page_size):
    total = db.scalar(select(func.count()).select_from(Notification).where(Notification.uid == uid))
    rows = db.scalars(select(Notification).where(Notification.uid == uid).order_by(
        Notification.created_at.desc(), Notification.notification_id.desc()).offset((page - 1) * page_size).limit(page_size))
    return {"items": [{"notificationId": row.notification_id, "applicationId": row.application_id,
                       "status": row.status, "rejectReason": row.reject_reason,
                       "version": row.version, "createdAt": row.created_at} for row in rows],
            "total": total, "page": page, "pageSize": page_size}
