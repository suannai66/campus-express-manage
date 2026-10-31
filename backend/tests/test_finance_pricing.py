"""正式报价规则与 B 模块接口集成测试。"""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pydantic import ValidationError
from app.modules.finance.services.pricing import PricingService
from app.modules.finance.services.order_payment import quote
from app.modules.orders.contract import Quote


class PricingTests(unittest.TestCase):
    def draft(self, **changes):
        return {"stationId": "station_cainiao", "deliveryAreaId": "zone_qinyuan",
                "size": "small", "weight": "1", "tip": 0, **changes}

    def test_all_routes_and_sizes(self):
        routes = [("station_cainiao", "zone_qinyuan", 200),
                  ("station_cainiao", "zone_zhuyuan", 300),
                  ("station_cainiao", "zone_public", 200),
                  ("station_sf", "zone_qinyuan", 300),
                  ("station_sf", "zone_zhuyuan", 200),
                  ("station_sf", "zone_public", 200)]
        for station, area, fee in routes:
            for size, extra in [("small", 0), ("medium", 100), ("large", 300)]:
                result = quote(self.draft(stationId=station, deliveryAreaId=area, size=size, tip=235))
                self.assertEqual((result["baseFee"], result["amount"]), (fee + extra, fee + extra + 235))
                Quote.model_validate(result)

    def test_weight_boundaries(self):
        for weight, expected in [("0.01", 200), ("1", 200), ("1.01", 300),
                                 ("2", 300), ("2.01", 400), ("30", 3100)]:
            self.assertEqual(quote(self.draft(weight=weight))["baseFee"], expected)

    def test_invalid_inputs(self):
        for field, values in {
            "tip": [True, "100", 100.0, -1, 99901],
            "weight": [True, 1.0, "0", "30.01", "NaN", "Infinity", "1e1", "1.001"],
            "size": ["SMALL", "unknown"], "stationId": ["unknown"],
            "deliveryAreaId": ["unknown"],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    quote(self.draft(**{field: value}))

    def test_expiry_version_and_object_input(self):
        before = datetime.now(timezone.utc)
        result = PricingService().quote(SimpleNamespace(**self.draft(tip=99900)))
        expiry = datetime.fromisoformat(result["expiresAt"].replace("Z", "+00:00"))
        self.assertGreaterEqual(expiry, before + timedelta(minutes=5))
        self.assertLessEqual(expiry, datetime.now(timezone.utc) + timedelta(minutes=5))
        self.assertEqual(result["pricingVersion"], "demo-20261030-v1")
        self.assertEqual(result["commissionRateBps"], 1000)
        self.assertEqual(result["amount"], 100100)
        self.assertTrue(result["demo"])
        self.assertNotEqual(result["quoteId"], quote(self.draft())["quoteId"])


class PricingIntegrationTests(unittest.TestCase):
    def test_real_service_quote_and_order_snapshot(self):
        from unittest.mock import patch
        import test_orders
        fixture = test_orders.OrderTests()
        with patch.object(test_orders, "TestPricing", PricingService):
            fixture.setUp()
        try:
            response = fixture.client.post("/api/orders/quote", json=fixture.body, headers=fixture.headers())
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual((result["baseFee"], result["tip"], result["amount"]), (300, 235, 535))
            order = fixture.create()
            self.assertEqual(order.status_code, 201, order.text)
            self.assertEqual(order.json()["amount"], 535)
            from app.modules.orders.entities import Order
            with fixture.sessions() as db:
                snapshot = db.get(Order, order.json()["orderId"])
                self.assertEqual(snapshot.pricing_version, "demo-20261030-v1")
                self.assertEqual(snapshot.commission_bps, 1000)
        finally:
            fixture.tearDown()
