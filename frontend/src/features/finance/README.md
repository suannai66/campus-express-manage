# 模拟收银台

MockCashier.vue 是统一的前端展示入口，内部提供微信和支付宝两种模拟方式。

- props：operation（recharge / withdrawal）、reference（模拟业务标识）、amount（整数分）、pending、error。
- events：confirm(channel)、close。渠道值为 wechat / alipay；由父用例负责资金请求。
- 组件不持有 Token、不调用资金接口；二维码在本地生成，仅编码模拟操作、引用标识和渠道。
  二维码不是实际收款码，也不是支付确认链接，扫码不会改变余额。
- WalletView 继续使用团队已有充值、确认、提现和查询接口，不新增请求字段。
  微信/支付宝选择仅为展示，不宣称后台已使用真实渠道或持久化渠道选择。
- 提现先显示模拟到账方式与收款凭证，再确认提交；没有让用户扫码付款。
- 充值关闭收银台不自动入账，同一弹窗内继续处理复用原幂等键；提交中禁止重复确认和关闭。
- 其他页面如果要展示收银台，需要显式集成组件；直接调用 HTTP API 不会弹窗。

验证：frontend 下执行 npm run test:finance；本机使用 PW_BROWSER_CHANNEL=msedge。
