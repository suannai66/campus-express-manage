"""公共事件维护：查看待办、原 ID 重试、单轮投递及历史事件补录。"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select
from app.database import SessionLocal
from app.events import dispatch_once, retry_dead
from app.events.models import Delivery
from app.events.service import Dispatcher
from app.events.wiring import register_defaults


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list", action="store_true", help="查看投递记录，默认仅 dead")
    action.add_argument("--retry", metavar="EVENT_ID", help="重试原事件的 dead 投递")
    action.add_argument("--once", action="store_true", help="最多投递 20 条")
    action.add_argument("--backfill", action="store_true", help="补录历史支付/退款事件，不移动资金")
    parser.add_argument("--consumer", choices=("orders", "finance", "fulfillment"))
    parser.add_argument("--status", choices=("pending", "processing", "succeeded", "dead"), default="dead")
    args = parser.parse_args()
    register_defaults()
    if args.retry:
        print(f"已恢复 {retry_dead(args.retry, consumer_name=args.consumer)} 条 dead 投递，保留原事件 ID")
    elif args.once:
        print(f"本轮尝试 {dispatch_once()} 条，投递结果请查看记录")
    elif args.backfill:
        from app.modules.finance.models import Payment, Refund
        dispatcher, total = Dispatcher(SessionLocal), 0
        with SessionLocal() as db:
            pages = sum((db.scalar(select(func.count()).select_from(model).where(model.event_status == "pending")) + 19) // 20
                        for model in (Payment, Refund))
        # 有限轮次覆盖原始待办，格式错误的前页不能阻止后页继续补录。
        for _ in range(pages + 2):
            total += dispatcher.backfill_once()
        print(f"已补录 {total} 条原始资金事件；补录失败的数据仍保持 pending，请检查日志")
    else:
        with SessionLocal() as db:
            query = select(Delivery).where(Delivery.status == args.status)
            if args.consumer:
                query = query.where(Delivery.consumer == args.consumer)
            rows = db.scalars(query.order_by(Delivery.next_attempt_at, Delivery.event_id).limit(100)).all()
            for row in rows:
                print(f"{row.event_id} {row.consumer} {row.status} attempts={row.attempts} "
                      f"nextAttemptAt={row.next_attempt_at} leaseUntil={row.lease_until} {row.last_error or ''}")
            print(f"共显示 {len(rows)} 条，最多显示 100 条；不输出事件正文")


if __name__ == "__main__":
    main()
