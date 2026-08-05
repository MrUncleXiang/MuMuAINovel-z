"""模型计价（估算）：用于流水线预算控制。

价格为估算值（USD/百万 tokens），按 1 USD = 7 CNY 折算为分（cents）。
已知模型取表内价格，未知模型用默认档。可在未来替换为供应商真实报价。
"""

# model 关键词 → (输入价 $/M, 输出价 $/M)
_PRICE_TABLE: dict[str, tuple[float, float]] = {
    "deepseek-v4-flash": (0.14, 0.28),
    "deepseek-v3": (0.27, 1.10),
    "deepseek-chat": (0.27, 1.10),
    "gpt-5.6": (1.25, 10.00),
    "gpt-5.5": (1.25, 10.00),
    "gpt-5": (1.25, 10.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "claude": (3.00, 15.00),
    "gemini-2.5": (1.25, 10.00),
    "gemini-2.0": (1.25, 10.00),
}

_DEFAULT_INPUT = 0.50  # $/M
_DEFAULT_OUTPUT = 2.00  # $/M
_CNY_PER_USD = 7.0


def estimate_cost_cents(model: str | None, prompt_tokens: int, completion_tokens: int) -> int:
    """估算一次调用的费用（人民币分）。"""
    key = ""
    if model:
        lowered = model.lower()
        for k, (i, o) in _PRICE_TABLE.items():
            if k in lowered:
                key = k
                break
    input_price, output_price = _PRICE_TABLE.get(key, (_DEFAULT_INPUT, _DEFAULT_OUTPUT))
    cost_usd = (prompt_tokens / 1_000_000) * input_price + (completion_tokens / 1_000_000) * output_price
    return int(round(cost_usd * _CNY_PER_USD * 100))
