"""实时信用，无缓存投影；只统计作为取件员收到的最近 30 单评价。"""
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select

from .models import Review


class CreditService:
    @staticmethod
    def get(db, uid):
        ratings = list(db.scalars(select(Review.rating).where(
            Review.reviewee_uid == uid, Review.reviewer_role == "publisher"
        ).order_by(Review.created_at.desc(), Review.id.desc()).limit(30)))
        if not ratings:
            return {"uid": uid, "score": None, "level": "new", "reviewCount": 0, "creditEligible": True}
        average = Decimal(sum(ratings)) / len(ratings)
        return {"uid": uid, "score": float(average.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "level": "restricted" if average < 3 else "normal" if average < 4 else "good",
                "reviewCount": len(ratings), "creditEligible": average >= 3}
