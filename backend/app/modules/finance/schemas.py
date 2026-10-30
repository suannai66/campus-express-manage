"""接口数据模型（骨架）。

约定：
- 金额一律以"分"为单位的整数传输（FR1.3），展示换算由前端负责；
- 金额、订单号等关键参数以服务端计算/校验为准，不信任前端结果（Q-05）；
- 外部事件字段属 B/C 契约（EV-3），联调前与团队书面固化。
"""

from pydantic import BaseModel, Field

# ---------- 定价与支付（F7） ----------


class QuoteRequest(BaseModel):
    """F3 创建订单时调用 POST /api/pay/quote（原型约定）。"""

    size: str = Field(description="包裹规格：小件 / 中件 / 大件")
    floor_tier: int = Field(ge=0, description="距离档位（查表参数）")
    tip_cent: int = Field(ge=0, description="小费（分）")


class QuoteResponse(BaseModel):
    """定价结果：金额 = 基础运费（距离/重量查表）+ 小费（FR2）。"""

    base_fee_cent: int = Field(description="基础运费（分）")
    tip_fee_cent: int = Field(description="小费（分）")
    amount_cent: int = Field(description="订单金额（分），≥ 起送价")


class FreezeRequest(BaseModel):
    """下单冻结请求（FR3）。金额以服务端定价为准，前端不传金额。"""

    order_id: str = Field(description="F3 订单号")


class FreezeResponse(BaseModel):
    """冻结结果；余额不足时拒绝（FR3.5），订单不进大厅。"""

    order_id: str
    status: str = Field(description="frozen 冻结成功 / rejected 余额不足")
    idempotency_key: str = Field(description="幂等键 <uid>:<order_id>")


# ---------- 钱包（F8） ----------


class BalanceResponse(BaseModel):
    """统一虚拟账户余额（FR1.2）：总余额 = 可用 + 冻结。"""

    available_cent: int = Field(description="可用余额（分）")
    frozen_cent: int = Field(description="冻结余额（分）")


class RechargeRequest(BaseModel):
    """发起充值（FR7）：渠道由服务端配置决定（config.CHANNEL_ACTIVE）。"""

    amount_cent: int = Field(gt=0, description="充值金额（分）")


class RechargeResponse(BaseModel):
    """充值单创建结果；等待渠道回调幂等入账（FR7.4）。"""

    out_trade_no: str = Field(description="充值单号（商户侧）")
    channel: str = Field(description="渠道：mock / alipay_sandbox")
    status: str = Field(description="pending / success / failed / closed")
    pay_url: str | None = Field(default=None, description="渠道收银台地址（模拟渠道）")


class WithdrawRequest(BaseModel):
    """申请提现（FR8.1）：金额为正且不超过可用余额，手续费 0。"""

    amount_cent: int = Field(gt=0, description="提现金额（分）")


class WithdrawResponse(BaseModel):
    """提现单创建结果（FR8.2）：处理中 → 模拟到账 → 扣冻结；失败解冻。"""

    withdraw_no: str = Field(description="提现单号")
    status: str = Field(description="processing / done / failed")


class LedgerPage(BaseModel):
    """流水分页（FR9）：单页 ≤ 100 条。"""

    items: list[dict] = Field(default_factory=list, description="流水条目")
    page: int
    page_size: int
    total: int


# ---------- 外部事件报文（B/C 契约，EV-3） ----------


class OrderCancelEvent(BaseModel):
    """订单取消事件（客户主动取消 / 超时自动取消）。取消判定权在 B/C，本模块只订阅（FR5.1）。"""

    # TODO(团队对齐) 与 B/C 固化字段：event_id、order_id、customer_uid、courier_uid、cancel_reason 等


class OrderCompleteEvent(BaseModel):
    """订单完结事件（F5 发布），触发结算（FR4）。"""

    # TODO(团队对齐) 与 B/C 固化字段：event_id、order_id、customer_uid、courier_uid、amount_cent 等


class FulfillTimeoutEvent(BaseModel):
    """履约超时事件（F5 负责 12h 超时检测），触发赔付 + 联动 F6 信用扣分（FR6.2）。"""

    # TODO(团队对齐) 与 B/C 固化字段：event_id、order_id、customer_uid、courier_uid 等
