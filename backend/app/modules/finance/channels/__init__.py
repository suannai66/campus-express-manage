"""端口/适配器层（EV-1）：统一渠道契约，验签/防重放/回调归一化封装在适配器之后。

- port.py            ChannelPort 契约 + InternalPaymentResult 归一化结果（调整 A）
- mock_cashier.py   模拟收银台（默认兜底常驻，C-06）
- alipay_sandbox.py 支付宝沙箱（后置；回调需公网可达，开发期内网穿透）
"""
