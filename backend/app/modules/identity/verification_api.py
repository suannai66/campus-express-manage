from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import Field, ValidationError, model_validator
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from ...common import Input, fail
from ...database import get_db
from .dependencies import current_identity
from . import verification as service
from .models import VerificationPhoto

router = APIRouter(prefix="/api", tags=["verification"])


class SubmitFields(Input):
    realName: str = Field(min_length=1, max_length=30)
    studentNo: str = Field(min_length=1, max_length=30)


class ReviewInput(Input):
    decision: Literal["approved", "rejected"]
    rejectReason: str | None = Field(default=None, max_length=500)
    version: int = Field(strict=True, gt=0)

    @model_validator(mode="after")
    def reason(self):
        if self.decision == "rejected" and not self.rejectReason:
            raise ValueError("驳回时必须填写具体理由")
        if self.decision == "approved" and self.rejectReason is not None:
            raise ValueError("通过审核时 rejectReason 必须为 null")
        return self


def validate_query(request, allowed=()):
    if set(request.query_params) - set(allowed):
        fail(422, "VALIDATION_ERROR", "查询包含未声明字段")
    for name in ("page", "pageSize"):
        raw = request.query_params.get(name)
        if raw is not None and (not raw.isascii() or not raw.isdigit()):
            fail(422, "VALIDATION_ERROR", "分页参数必须为正整数", {name: "请输入正整数"})


@router.post("/auth/verification-applications", status_code=201)
async def submit(request: Request, user=Depends(current_identity), db: Session = Depends(get_db)):
    validate_query(request)
    try:
        async with request.form(max_files=1, max_fields=2, max_part_size=4096) as form:
            if set(form) != {"realName", "studentNo", "photo"} or len(form.multi_items()) != 3:
                fail(422, "VALIDATION_ERROR", "请仅提交姓名、学号和一张照片")
            photo = form["photo"]
            if not isinstance(photo, UploadFile):
                fail(422, "VALIDATION_ERROR", "请上传证件照片", {"photo": "缺少照片文件"})
            fields = SubmitFields.model_validate({"realName": form["realName"], "studentNo": form["studentNo"]})
            content = await photo.read(service.MAX_PHOTO_BYTES + 1)
    except ValidationError:
        fail(422, "VALIDATION_ERROR", "姓名和学号须为 1～30 个非空字符", {"realName": "请检查姓名", "studentNo": "请检查学号"})
    except HTTPException as error:
        if error.status_code != 400: raise
        fail(422, "VALIDATION_ERROR", "资料格式不正确，请提交姓名、学号和一张照片")
    return await run_in_threadpool(service.submit_application, db, user.uid, fields.realName, fields.studentNo, content)


@router.get("/auth/verification-applications")
def history(request: Request, page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100),
            user=Depends(current_identity), db: Session = Depends(get_db)):
    validate_query(request, ("page", "pageSize"))
    return service.application_page(db, page, pageSize, uid=user.uid)


@router.get("/auth/verification-notifications")
def notifications(request: Request, page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100),
                  user=Depends(current_identity), db: Session = Depends(get_db)):
    validate_query(request, ("page", "pageSize"))
    return service.notification_page(db, user.uid, page, pageSize)


@router.get("/admin/verification-applications")
def admin_list(request: Request, status: Literal["pending", "approved", "rejected"] | None = None,
               page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100),
               user=Depends(current_identity), db: Session = Depends(get_db)):
    service.require_admin(user)
    validate_query(request, ("status", "page", "pageSize"))
    return service.application_page(db, page, pageSize, status=status)


@router.get("/admin/verification-applications/{application_id}")
def admin_detail(application_id: str, request: Request, user=Depends(current_identity), db: Session = Depends(get_db)):
    service.require_admin(user)
    validate_query(request)
    return service.application_view(service.find_application(db, application_id), full=True)


@router.post("/admin/verification-applications/{application_id}/review")
def review(application_id: str, body: ReviewInput, request: Request,
           user=Depends(current_identity), db: Session = Depends(get_db)):
    service.require_admin(user)
    validate_query(request)
    return service.review_application(db, application_id, user.uid, body.decision, body.rejectReason, body.version)


@router.get("/auth/verification-applications/{application_id}/photo")
def photo(application_id: str, request: Request, user=Depends(current_identity), db: Session = Depends(get_db)):
    validate_query(request)
    application = service.find_application(db, application_id)
    if user.uid != application.uid and user.role != "admin":
        fail(404, "NOT_FOUND", "认证申请不存在或不可访问")
    photo = db.get(VerificationPhoto, application_id)
    if not photo:
        fail(404, "NOT_FOUND", "证件照片不存在")
    return Response(photo.content, media_type=photo.content_type, headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline; filename=verification." + ("png" if photo.content_type == "image/png" else "jpg")})
