"""读序明细：合并后的正文节点先后、边注读取位置与续接争议关系。

同一原文位置的重复导出已合并；同一位置的矛盾导出、续接分叉、断引、
回环与引用先后无法确认都在争议事实中指出关系，不按导出顺序任选。
"""

from .contract import Row
from .narration import prepare


def _order_id(key: tuple[int, int]) -> str:
    return f"order:{key[0]}-{key[1]}"


def _order_fact(node: Row, model: Row) -> Row:
    key = node["key"]
    fact = {
        "fact_id": _order_id(key),
        "position": {"start": node["start"], "end": node["end"]},
        "paragraph": node["paragraph"],
        "page": node["page"],
        "layout_order": node["layout_order"],
        "member_exports": node["exports"],
        "chain": model["chain_of"][key],
        "predecessor": None,
        "successor": _order_id(node["successor"]) if node["successor"] else None,
        "continuity": node["continuity"],
        "segment": f"text:{node['start']}-{node['end']}",
        "status": "to_verify" if node["contradictory"] or node["paragraph"] is None
                  or node["continuity"] in ("fork", "broken", "loop") else "confirmed",
    }
    predecessor = model["predecessor_of"].get(key)
    if predecessor is not None:
        fact["predecessor"] = _order_id(predecessor)
    if len(node["texts"]) > 1:
        fact["texts"] = list(node["texts"])
    if len(node["paragraphs"]) > 1:
        fact["paragraphs"] = list(node["paragraphs"])
    if node["broken_target"] is not None:
        fact["broken_target"] = node["broken_target"]
    if node["continuity"] == "fork" and node["targets"]:
        fact["targets"] = list(node["targets"])
    candidates = model["predecessor_candidates"].get(key)
    if candidates:
        fact["predecessor_candidates"] = [_order_id(candidate) for candidate in candidates]
    return fact


def _note_fact(placement: Row) -> Row:
    note = placement["note"]
    fact = {
        "fact_id": f"note:{note['id']}",
        "position": {"start": note["start"], "end": note["end"]},
        "citations": placement["citations"],
        "status": placement["status"],
    }
    if placement["status"] != "no_citation":
        fact["read_at"] = placement["read_at"]
        fact["candidates"] = placement["candidates"]
        fact["traced_from"] = placement["traced_from"]
        fact["inserted_after"] = f"text:{placement['anchor'][0]}-{placement['anchor'][1]}"
        fact["position_confirmed"] = placement["position_confirmed"]
    return fact


def _dispute_facts(dispute: Row) -> Row:
    kind = dispute["type"]
    if kind == "contradictory_exports":
        node = dispute["node"]
        return {"fact_id": f"dispute:contradictory_exports:{node['start']}-{node['end']}",
                "type": kind,
                "position": {"start": node["start"], "end": node["end"]},
                "exports": node["exports"],
                "texts": node["texts"],
                "paragraphs": node["paragraphs"],
                "layouts": [{"page": page, "layout_order": order}
                            for page, order in node["layouts"]]}
    if kind == "fork" and "target" in dispute:
        return {"fact_id": f"dispute:fork:{dispute['target'][0]}-{dispute['target'][1]}",
                "type": kind,
                "target": _order_id(dispute["target"]),
                "predecessors": [_order_id(key) for key in dispute["predecessors"]]}
    if kind == "fork":
        node = dispute["node"]
        return {"fact_id": f"dispute:fork:{node['start']}-{node['end']}",
                "type": kind,
                "source": _order_id(node["key"]),
                "targets": dispute["targets"]}
    if kind == "broken_continuation":
        node = dispute["node"]
        return {"fact_id": f"dispute:broken_continuation:{node['start']}-{node['end']}",
                "type": kind,
                "source": _order_id(node["key"]),
                "missing_target": dispute["target"]}
    if kind == "loop":
        members = dispute["members"]
        return {"fact_id": f"dispute:loop:{members[0][0]}-{members[0][1]}",
                "type": kind,
                "members": [_order_id(key) for key in members]}
    if kind == "citation_order":
        return {"fact_id": f"dispute:citation_order:{dispute['note']['id']}",
                "type": kind,
                "note": dispute["note"]["id"],
                "candidates": dispute["candidates"]}
    citation = dispute["citation"]
    return {"fact_id": f"dispute:broken_citation:{citation['id']}",
            "type": "broken_citation",
            "citation": citation["id"],
            "note": citation["note"],
            "anchor": citation["anchor"]}


def build_facts(data: Row) -> list[Row]:
    model = prepare(data)
    facts = [_order_fact(node, model) for node in model["nodes"]]
    facts += [_note_fact(model["placements"][note["id"]]) for note in model["notes"]]
    facts += [_dispute_facts(dispute) for dispute in model["disputes"]]
    return facts
