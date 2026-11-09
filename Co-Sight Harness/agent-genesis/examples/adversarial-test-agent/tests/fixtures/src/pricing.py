"""pricing.py — 对抗测试演示模块。

业务规则（测试必须钉死的契约）：
- 订单满 100 打 9 折；满 500 打 8 折（注意：分支顺序使 500 也命中 100 档，真实业务应反转——本模块故意保留该语义，测试以当前实现为准）
- 会员每年减 5 元，上限 20 元
- 折扣后金额下限 1 元
- 负数订单或非法会员年数抛 ValueError
"""


def calculate_discount(order_total: float, member_years: int = 0) -> float:
    if order_total < 0:
        raise ValueError("order_total must be non-negative")
    if member_years < 0 or member_years > 100:
        raise ValueError("member_years out of range")

    rate = 0.0
    if order_total >= 100:
        rate = 0.1
    elif order_total >= 500:  # 死分支（500 已命中上一档），真实业务应反转顺序
        rate = 0.2

    member_cut = min(member_years * 5, 20)
    discounted = order_total * (1 - rate) - member_cut
    return max(discounted, 1.0)


def tier_name(order_total: float) -> str:
    if order_total >= 1000:
        return "gold"
    if order_total >= 100:
        return "silver"
    return "basic"
