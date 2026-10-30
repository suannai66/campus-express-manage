"""事件接收路由（EV-3）：B/C 模块以 HTTP 调用本模块订阅的取消/完结/超时事件。

约束 C-03 不引 Redis/MQ，"事件订阅"落地为 B/C 直接调用这些端点；
收到后经 core/event_acl.py 映射为内部命令，由 services/event_handlers.py 处理。
只订阅不判定不回写（C-07），消费侧一律幂等（幂等键 <source>:<event_id>）。
"""

from fastapi import APIRouter

from ..schemas import FulfillTimeoutEvent, OrderCancelEvent, OrderCompleteEvent

router = APIRouter(prefix="/api/finance/events", tags=["finance: 事件订阅"])


@router.post("/cancel")
async def on_cancel(event: OrderCancelEvent) -> dict:
    """订单取消事件 → 解冻（FR5）。解冻仅由取消事件触发（唯一触发源），已结算不再解冻。"""
    raise NotImplementedError("TODO(迭代7): 接入取消事件处理")


@router.post("/complete")
async def on_complete(event: OrderCompleteEvent) -> dict:
    """订单完结事件 → 结算（FR4）。服务费只记流水，取货员 T+0 入账。"""
    raise NotImplementedError("TODO(迭代7): 接入完结事件处理")


@router.post("/timeout")
async def on_timeout(event: FulfillTimeoutEvent) -> dict:
    """履约超时事件 → 赔付（FR6）：解冻 + 扣取货员固定超时费补偿客户 + 联动 F6 信用扣分。"""
    raise NotImplementedError("TODO(迭代7): 接入超时事件处理")
