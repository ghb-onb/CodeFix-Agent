"""订单结算模块 —— 故意留了一个折扣计算 Bug，供 CodeFix Agent 演示。

Bug 说明：apply_discount 把「折扣率」当成「折后系数」直接相乘。
于是 discount_rate=0.1（本意九折）算出来只剩一成价，
discount_rate=0.0（本意不打折）直接算成 0 元。
"""

from __future__ import annotations

TAX_RATE = 0.06


def apply_discount(unit_price: float, quantity: int, discount_rate: float) -> float:
    """按折扣率计算折后金额。discount_rate=0.1 表示优惠 10%。"""
    subtotal = unit_price * quantity
    total = subtotal * discount_rate
    return round(total, 2)


def calculate_order_total(unit_price: float, quantity: int, discount_rate: float) -> float:
    """折后金额再加税，返回含税总价。"""
    discounted = apply_discount(unit_price, quantity, discount_rate)
    return round(discounted * (1 + TAX_RATE), 2)
