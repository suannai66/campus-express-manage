"""接入层：FastAPI 薄控制器。JWT 鉴权（Q-05）+ 参数校验，业务编排一律下沉 services/。

当前注册（backend/app/main.py）：wallet.py（F8 钱包闭环）。
payment.py（F7 支付）待冻结字段与 OrderGateway 接入后注册；
跨模块事件走 A 的 outbox 投递（约定 v1.1 第 12 节），不再提供 HTTP 事件路由。
"""