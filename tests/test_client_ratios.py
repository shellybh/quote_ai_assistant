from eval.client_ratios import price_history, ratio_line


def _line(price, discount=0):
    return {"code": "01.09.001.0230", "description": "סעיף", "unit": "מ\"ר",
            "quantity": 1, "unit_price": price, "discount_percent": discount}


def test_median_of_zero_gives_no_ratio():
    # Past line at 100% discount: net price 0, so the median is 0.
    history = price_history([{"id": "p1", "line_items": [_line(50, discount=100)]}])
    row = ratio_line(_line(100), history, {})
    assert row["history_ratio"] is None
    assert row["history_count"] == 1


def test_ratio_against_the_median():
    history = price_history([{"id": "p1", "line_items": [_line(40), _line(60)]}])
    assert ratio_line(_line(100), history, {})["history_ratio"] == 2
