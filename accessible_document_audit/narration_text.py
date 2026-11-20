"""连续文本：按确认的续接先后组织朗读序列，保留语言区间与待核标记。

朗读员据此分清哪里可以继续读、哪里需要回查原稿：continuity 为
confirmed/end 时可继续，fork/broken/loop 或任何 to_verify 都需回查；
语言待核不影响仍可接续的正文，读序争议也不抹掉已确认的语言。
"""

from .contract import Row
from .narration import language_intervals, prepare


def _segment_id(start: int, end: int) -> str:
    return f"text:{start}-{end}"


def _body_fact(sequence: int, node: Row, model: Row) -> Row:
    start, end = node["start"], node["end"]
    unit = model["unit_of_node"][node["key"]]
    intervals = language_intervals(unit, start, end, parts=[node])
    review = []
    if node["contradictory"]:
        review.append("contradictory exports")
    if node["paragraph"] is None:
        review.append("paragraph attribution disputed")
    if node["continuity"] in ("fork", "loop"):
        review.append(node["continuity"])
    elif node["continuity"] == "broken":
        review.append("broken continuation")
    if any(interval["status"] == "to_verify" for interval in intervals):
        review.append("language to_verify")
    fact = {
        "fact_id": _segment_id(start, end),
        "sequence": sequence,
        "kind": "body",
        "paragraph": node["paragraph"],
        "page": node["page"],
        "layout_order": node["layout_order"],
        "position": {"start": start, "end": end},
        "text": node["text"],
        "text_status": "confirmed" if len(node["texts"]) == 1 else "to_verify",
        "member_exports": node["exports"],
        "language": intervals,
        "continues_to": (_segment_id(*node["successor"])
                         if node["successor"] is not None else None),
        "continuity": node["continuity"],
        "chain": model["chain_of"][node["key"]],
        "needs_review": bool(review),
        "review_reasons": review,
    }
    if len(node["texts"]) > 1:
        fact["variants"] = list(node["texts"])
    if node["broken_target"] is not None:
        fact["broken_target"] = node["broken_target"]
    if node["continuity"] == "fork":
        fact["targets"] = list(node["targets"])
    return fact


def _note_fact(sequence: int, placement: Row) -> Row:
    note = placement["note"]
    review = []
    if not placement["position_confirmed"]:
        review.append("citation order unconfirmed")
    if any(interval["status"] == "to_verify"
           for interval in placement["language_intervals"]):
        review.append("language to_verify")
    fact = {
        "fact_id": f"text:note:{note['id']}",
        "sequence": sequence,
        "kind": "margin_note",
        "note": note["id"],
        "position": {"start": note["start"], "end": note["end"]},
        "text": note["text"],
        "language": placement["language_intervals"],
        "inserted_after": _segment_id(*placement["anchor"]),
        "read_at": placement["read_at"],
        "candidates": placement["candidates"],
        "traced_from": placement["traced_from"],
        "position_confirmed": placement["position_confirmed"],
        "needs_review": bool(review),
        "review_reasons": review,
    }
    return fact


def build_facts(data: Row) -> list[Row]:
    model = prepare(data)
    unit_by_note = {unit["id"]: unit for unit in model["units"] if unit["kind"] == "note"}
    for placement in model["placements"].values():
        note = placement["note"]
        placement["language_intervals"] = language_intervals(
            unit_by_note[note["id"]], note["start"], note["end"])
    facts = []
    for sequence, entry in enumerate(model["sequence"], start=1):
        if entry["kind"] == "body":
            facts.append(_body_fact(sequence, entry["node"], model))
        else:
            facts.append(_note_fact(sequence, entry["placement"]))
    return facts
