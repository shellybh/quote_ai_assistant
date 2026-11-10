"""A+ payment baseline: stages found by a regex, no AI. Eval only.

In the order they appear: a number with "%" is a percent stage, a masked
label ("[סכום1]") an amount stage, and "יתרה" / "השאר" the remainder.
"""

import re

TOKEN = re.compile(r"(?P<percent>\d+(?:\.\d+)?)\s*%|(?P<ref>\[סכום\d+\])|(?P<rest>היתרה|יתרה|והשאר|השאר)")


def regex_payment(text: str) -> list[dict]:
    stages = []
    for m in TOKEN.finditer(text):
        if m["percent"]:
            stages.append({"percent": float(m["percent"])})
        elif m["ref"]:
            stages.append({"amount_ref": m["ref"]})
        else:
            stages.append({"is_remainder": True})
    return stages
