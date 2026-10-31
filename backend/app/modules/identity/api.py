from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy.orm import Session

from ...common import Input, fail
from ...database import get_db
from .dependencies import current_identity
from .service import verification_status

def reject_query(request: Request):
    if request.query_params:
        fail(422, "VALIDATION_ERROR", "身份接口不接受查询参数")


router = APIRouter(prefix="/api/auth", tags=["identity"], dependencies=[Depends(reject_query)])


class CodeRequest(Input):
    phone: str = Field(pattern=r"^1[3-9][0-9]{9}$")
    purpose: Literal["register", "login"]


class Credentials(Input):
    phone: str = Field(pattern=r"^1[3-9][0-9]{9}$")
    code: str = Field(pattern=r"^[0-9]{6}$")


def service(request):
    result = getattr(request.app.state, "identity_service", None)
    if result is None:
        fail(503, "DEPENDENCY_UNAVAILABLE", "身份服务尚未接入")
    return result


@router.post("/codes")
def send_code(body: CodeRequest, request: Request, db: Session = Depends(get_db)):
    return service(request).send_code(db, body.phone, body.purpose)


@router.post("/register", status_code=201)
def register(body: Credentials, request: Request, db: Session = Depends(get_db)):
    return service(request).register(db, body.phone, body.code)


@router.post("/login")
def login(body: Credentials, request: Request, db: Session = Depends(get_db)):
    return service(request).login(db, body.phone, body.code)


@router.get("/current")
def current(user=Depends(current_identity)):
    return {"uid": user.uid, "phone": user.phone, "nickname": user.nickname, "role": user.role}


@router.post("/logout")
def logout(request: Request, body: Input | None = None, user=Depends(current_identity), db: Session = Depends(get_db)):
    return service(request).logout(db, user)


@router.get("/verify-status")
def verify_status(user=Depends(current_identity), db: Session = Depends(get_db)):
    return verification_status(db, user.uid)
