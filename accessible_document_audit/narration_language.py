"""语言明细：逐段给出语言范围、实际声明和无法确认的原因。

每个文字单元（段落、边注、归属有争议的位置）都按原文起止位置列出
解析后的语言区间与支撑声明；同层矛盾的交叠文字标为待核并给出原因，
悬空或横跨多个单元的声明也逐条列出，便于回查原稿。
"""

from .contract import Row
from .narration import ATTRIBUTION_DISPUTED, NO_TEXT, _slice_text, prepare


def _unit_fact(unit: Row) -> Row:
    ranges = []
    for outcome in unit["resolved"]:
        entry = {"start": outcome["start"], "end": outcome["end"],
                 "language": outcome["language"], "source": outcome["source"],
                 "status": outcome["status"],
                 "declarations": outcome["declarations"],
                 "text": _slice_text(unit["parts"], outcome["start"], outcome["end"])}
        if outcome["status"] == "to_verify":
            entry["reason"] = outcome["reason"]
            entry["claims"] = outcome["claims"]
        ranges.append(entry)
    fact = {"ranges": ranges}
    fact["declarations"] = sorted(
        {decl_id for outcome in unit["resolved"] for decl_id in outcome["declarations"]}
        | {item["declaration"] for item in unit["unconfirmable"]})
    unconfirmable = list(unit["unconfirmable"])
    if unit["kind"] == "position":
        unconfirmable.append({"declaration": None, "reason": ATTRIBUTION_DISPUTED,
                              "start": unit["ranges"][0][0], "end": unit["ranges"][0][1],
                              "language": None})
    fact["unconfirmable"] = unconfirmable
    return fact


def build_facts(data: Row) -> list[Row]:
    model = prepare(data)
    facts = []
    units = sorted(model["units"],
                   key=lambda unit: (min(start for start, _ in unit["ranges"]),
                                     unit["kind"] != "paragraph", unit["id"]))
    for unit in units:
        detail = _unit_fact(unit)
        segments = []
        if unit["kind"] == "paragraph":
            segments = [f"text:{part['start']}-{part['end']}" for part in unit["parts"]]
        elif unit["kind"] == "note":
            placed = model["placements"][unit["id"]]
            if placed["status"] != "no_citation":
                segments = [f"text:note:{unit['id']}"]
        else:
            segments = [f"text:{unit['id']}"]
        if unit["kind"] == "paragraph":
            fact = {"fact_id": f"lang:{unit['id']}", "paragraph": unit["id"],
                    "pages": unit["pages"], "segments": segments}
        elif unit["kind"] == "note":
            fact = {"fact_id": f"lang:note:{unit['id']}", "note": unit["id"],
                    "segments": segments}
        else:
            fact = {"fact_id": f"lang:position:{unit['id']}", "segments": segments}
        fact.update(detail)
        facts.append(fact)
    for decl in model["dangling_declarations"]:
        facts.append({"fact_id": f"lang:declaration:{decl['id']}",
                      "declaration": decl["id"], "level": decl["level"],
                      "language": decl["language"],
                      "range": {"start": decl["start"], "end": decl["end"]},
                      "status": "unconfirmable", "reason": NO_TEXT})
    return facts
