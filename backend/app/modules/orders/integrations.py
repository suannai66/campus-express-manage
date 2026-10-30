"""A/D 的替代适配层。external 模式不会降级为演示身份或演示付款。

实际团队契约落地后只需调整本文件的字段映射，不改订单业务。
"""
import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request as HttpRequest, urlopen

from fastapi import HTTPException, Request

from .schemas import OrderDraft


def dependency_mode():
    mode = os.getenv("F3_DEPENDENCY_MODE", "demo")
    if mode not in {"demo", "external"}:
        raise HTTPException(503, "F3 依赖模式配置错误")
    return mode


@dataclass
class Identity:
    uid: str
    nickname: str
    verified: bool


def remote_json(base_env, path, request, body=None):
    base = os.getenv(base_env, "").rstrip("/")
    if not base:
        raise HTTPException(503, "协作接口尚未配置，请联系开发同学")
    headers = {"Content-Type": "application/json"}
    for name in ("authorization", "cookie", "idempotency-key"):
        if value := request.headers.get(name):
            headers[name] = value
    remote = HttpRequest(
        base + path, headers=headers,
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urlopen(remote, timeout=8) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code in {401, 403}:
            raise HTTPException(error.code, "请登录并完成学生认证") from error
        raise HTTPException(502, "协作服务未能完成请求，请稍后重试") from error
    except (URLError, TimeoutError, ValueError, OSError) as error:
        raise HTTPException(503, "协作服务暂时不可用，请稍后重试") from error


def current_identity(request: Request):
    if dependency_mode() == "demo":
        state = request.cookies.get("f3_demo_session", "verified")
        if state == "guest":
            raise HTTPException(401, "请先登录后再发布需求")
        return Identity("demo-student-b", "演示同学", state == "verified")
    user = remote_json("F3_IDENTITY_BASE_URL", "/api/auth/current", request)
    verification = remote_json("F3_IDENTITY_BASE_URL", "/api/auth/verify-status", request)
    if not isinstance(user, dict) or not user.get("uid") or not isinstance(verification, dict):
        raise HTTPException(502, "身份接口返回格式不正确")
    return Identity(str(user["uid"]), user.get("nickname", "同学"), verification.get("verified") is True)


def quote(draft: OrderDraft, request: Request):
    if dependency_mode() == "demo":
        # 临时计费规则，不作为 D 的正式运费规则。
        base = {"小件": 200, "中件": 300, "大件": 500}[draft.size]
        base += max(0, int(draft.weight.__ceil__()) - 1) * 100
    else:
        result = remote_json("F3_PAYMENT_BASE_URL", "/api/pay/quote", request,
                             draft.model_dump(mode="json"))
        base = result.get("baseFeeCents") if isinstance(result, dict) else None
        if type(base) is not int or not 0 < base <= 100000:
            raise HTTPException(502, "费用接口返回格式不正确")
    tip = int(draft.tip * 100)
    return {"baseFeeCents": base, "tipCents": tip, "amountCents": base + tip,
            "pricingSource": dependency_mode()}


def prepay(order, request: Request):
    if dependency_mode() == "demo":
        return {"mode": "demo", "orderId": order.id, "amountCents": order.amount_cents}
    result = remote_json("F3_PAYMENT_BASE_URL", "/api/pay/prepay", request, {
        "orderId": order.id, "amountCents": order.amount_cents, "uid": order.publisher_uid,
    })
    return {"mode": "external", "orderId": order.id, "payment": result}
