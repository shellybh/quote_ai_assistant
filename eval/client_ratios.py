"""What the app does on the phone before a review request (SPEC 6, 9.2):
turn the proposal's prices into ratios, so no price is sent.

Used only by the evaluation and the tests, which start from proposals with
prices (eval/datasets, data/demo). The server itself never sees a price.
The app's own implementation is in Dart; this mirrors its rule: the median
of the code's unit prices (after discount) in the *other* proposals.
"""

import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping


def net_price(line: Mapping) -> float:
    return line["unit_price"] * (1 - line.get("discount_percent", 0) / 100)


def price_history(proposals: Iterable[Mapping], exclude_id: str | None = None) -> dict[str, list[float]]:
    prices: dict[str, list[float]] = defaultdict(list)
    for p in proposals:
        if p.get("id") == exclude_id:
            continue
        for li in p["line_items"]:
            if li["unit_price"] > 0:
                prices[li["code"]].append(net_price(li))
    return prices


def ratio_line(line: Mapping, history: Mapping[str, list[float]],
               catalog_prices: Mapping[str, float]) -> dict:
    """One request line: code, text, unit, quantity and the two ratios."""
    price = net_price(line)
    past = history.get(line["code"], [])
    # A 100% discount makes a past net price 0; a median of 0 gives no ratio.
    past_median = statistics.median(past) if past else 0
    catalog_price = line.get("catalog_price", catalog_prices.get(line["code"]))
    return {
        "code": line["code"],
        "description": line["description"],
        "unit": line["unit"],
        "quantity": line["quantity"],
        "history_ratio": price / past_median if past_median > 0 and price > 0 else None,
        "history_count": len(past),
        "catalog_ratio": price / catalog_price if catalog_price and price > 0 else None,
    }
