"""折扣逻辑的验收测试。修复前全红，修复后 4/4 全绿。"""

from buggy_code import apply_discount, calculate_order_total


def test_no_discount_keeps_subtotal():
    """不打折时，折后金额必须等于小计。"""
    assert apply_discount(100.0, 2, 0.0) == 200.0


def test_ten_percent_off():
    """九折：100 元优惠 10% 后是 90 元。"""
    assert apply_discount(100.0, 1, 0.1) == 90.0


def test_twenty_percent_off():
    """八折：250 元 × 4 件 = 1000 元，优惠 20% 后是 800 元。"""
    assert apply_discount(250.0, 4, 0.2) == 800.0


def test_order_total_includes_tax():
    """200 元小计，九折后 180 元，加 6% 税 = 190.8 元。"""
    assert calculate_order_total(100.0, 2, 0.1) == 190.8
