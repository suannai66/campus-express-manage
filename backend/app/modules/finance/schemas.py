"""接口数据模型（对齐《团队接口约定》v1.1）。

约定：
- 金额一律为整数"分"，字段名 amount/balance（FR1.3）；不使用浮点数计算资金；
- 时间返回 UTC ISO 8601（Z）；分页参数 page / pageSize（默认 20、最大 100）；
- 创建成功 201，其余正常响应 200；成功直接返回对象，不套 data/code 层；
- 请求未声明的字段拒绝（422）；枚举区分大小写。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ---------- 钱包（F8，团队接口约定 v1.1 第 10 节） ----------


class WalletResponse(BaseModel):
    """GET /api/wallet：统一虚拟账户余额。"""

    balance: int = Field(description="可用余额（分）")
    currency: str = Field(default="CNY", description="币种，恒为 CNY")
    demo: bool = Field(default=True, description="演示模式，恒为 true（虚拟资金）")


class RechargeRequest(BaseModel):
    """POST /api/wallet/recharge：发起充值。金额整数 1 ~ 100000（分）。

    strict：拒绝布尔、字符串、小数（约定：金额拒绝字符串、小数、布尔值、NaN，返回 422）。
    """

    model_config = ConfigDict(extra="forbid")

    amount: int = Field(strict=True, ge=1, le=100000, description="充值金额（分）")


class RechargeResponse(BaseModel):
    """充值单创建结果（201）：等待 confirm 幂等入账。"""

    rechargeId: str = Field(description="充值单号")
    amount: int = Field(description="充值金额（分）")
    status: str = Field(description="pending")
    demo: bool = Field(default=True, description="演示模式，恒为 true")


class RechargeConfirmResponse(BaseModel):
    """POST /api/wallet/recharge/{rechargeId}/confirm：演示专用确认入账结果。"""

    rechargeId: str
    amount: int
    status: str = Field(description="succeeded")


class WithdrawRequest(BaseModel):
    """POST /api/wallet/withdraw：申请提现。金额整数 1 ~ 100000 且不超过可用余额。

    strict：拒绝布尔、字符串、小数（约定：金额拒绝字符串、小数、布尔值、NaN，返回 422）。
    """

    model_config = ConfigDict(extra="forbid")

    amount: int = Field(strict=True, ge=1, le=100000, description="提现金额（分）")


class WithdrawResponse(BaseModel):
    """提现单创建结果（201）：先扣可用余额，后台任务 ≥3 秒后标记 succeeded。"""

    withdrawId: str = Field(description="提现单号")
    amount: int = Field(description="提现金额（分）")
    status: str = Field(description="processing")


class WithdrawalQueryResponse(BaseModel):
    """GET /api/wallet/withdrawals/{withdrawId}：提现单状态。"""

    withdrawId: str
    amount: int
    status: str = Field(description="processing / succeeded / failed")


class TransactionItem(BaseModel):
    """流水条目（GET /api/wallet/transactions）。"""

    transactionId: str = Field(description="流水号（不透明字符串）")
    type: str = Field(description="recharge / payment / refund / settlement / withdrawal")
    direction: str = Field(description="in 入账 / out 出账")
    amount: int = Field(description="变动额（分），恒为正")
    balanceAfter: int = Field(description="变动后余额快照（分）")
    orderId: str | None = Field(default=None, description="关联订单号；钱包类流水为 null")
    referenceId: str = Field(description="业务单号（充值单/提现单/幂等键）")
    createdAt: datetime = Field(description="UTC ISO 8601 时间")


class TransactionsPage(BaseModel):
    """流水分页：page 从 1 开始，pageSize 默认 20、最大 100。"""

    items: list[TransactionItem] = Field(default_factory=list)
    page: int
    pageSize: int
    total: int


# ---------- 支付（F7，团队接口约定 v1.1 第 8/10 节，随冻结字段迭代实现） ----------


class PrepayRequest(BaseModel):
    """POST /api/pay/prepay：余额支付。B 已完成支付预占后调用。"""

    model_config = ConfigDict(extra="forbid")

    orderId: str = Field(min_length=1, max_length=100, description="B 的订单号")
    paymentRequestId: str = Field(min_length=1, max_length=100, description="B 支付预占生成的请求标识")


class PrepayResponse(BaseModel):
    """支付结果：同步返回 succeeded（code=null）或确定失败的 failed（code 带原因）。"""

    paymentId: str
    orderId: str
    amount: int
    status: str = Field(description="succeeded / failed")
    code: str | None = Field(default=None, description="失败原因，如 INSUFFICIENT_BALANCE")