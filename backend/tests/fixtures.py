"""测试用 A/D 替身，不注册到正式应用。"""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
from uuid import uuid4
from app.common import fail, iso, now
from app.modules.orders.integrations import Identity

class TestIdentity:
    def current(self, request, db):
        token = request.headers.get("Authorization", "")
        if token not in {"Bearer alice", "Bearer bob", "Bearer unverified"}:
            fail(401, "AUTH_REQUIRED", "请先登录")
        uid = token.split()[1]
        return Identity(uid, verified=uid != "unverified")

class TestPricing:
    def quote(self, draft):
        routes = {"station_cainiao": {"zone_qinyuan": 200, "zone_zhuyuan": 300, "zone_public": 200}, "station_sf": {"zone_qinyuan": 300, "zone_zhuyuan": 200, "zone_public": 200}}
        base = routes[draft.stationId][draft.deliveryAreaId] + {"small": 0, "medium": 100, "large": 300}[draft.size]
        base += max(0, int(Decimal(draft.weight).to_integral_value(rounding=ROUND_CEILING)) - 1) * 100
        return {"quoteId": str(uuid4()), "pricingVersion": "demo-20261030-v1", "baseFee": base, "tip": draft.tip, "amount": base + draft.tip, "commissionRateBps": 1000, "expiresAt": iso(now() + timedelta(minutes=5)), "demo": True}
