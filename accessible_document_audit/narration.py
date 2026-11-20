"""有声版朗读方案的共用解析：正文续接、边注引用、段落归属与位置语言声明。

材料是同一份导出 JSON：

- ``document_language``：文档默认语言。
- ``fragments``：正文片段，含段落归属、页内排布（page/layout_order）、
  原文起止位置（start/end）与可选的续接目标（continues_to）。
- ``margin_notes``：边注，自带原文位置与可选的自身语言。
- ``citations``：正文对边注的引用，含引用处锚点与引用标记的页内排布。
- ``language_declarations``：语言声明，只有原文起止位置和层级
  （phrase 词句 / paragraph 段落），没有预先切好的词句。

解析结果供 narration-text、narration-reading-order、narration-language
三条数据链共用，保证三份结果按原文位置互相查证。
"""

from __future__ import annotations

from .contract import Row, index_rows, integer, read_rows, text

LEVELS = ("phrase", "paragraph")

CONFLICT_PHRASE = "conflicting phrase declarations"
CONFLICT_PARAGRAPH = "conflicting paragraph declarations"
SPANS_UNITS = "declaration spans multiple text units"
NO_TEXT = "no text at declared range"
ATTRIBUTION_DISPUTED = "paragraph attribution disputed"


def _optional_rows(data: Row, field: str) -> list[Row]:
    rows = data.get(field, [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{field} must contain JSON objects")
    return rows


def _unique(rows: list[Row]) -> list[Row]:
    return list(index_rows(rows, "id").values())


def _range(row: Row) -> tuple[int, int]:
    start = integer(row, "start", minimum=0)
    end = integer(row, "end", minimum=1)
    if end <= start:
        raise ValueError("end must be greater than start")
    return start, end


def _position_text(row: Row, start: int, end: int) -> str:
    value = text(row, "text")
    if len(value) != end - start:
        raise ValueError("text length must match the declared position range")
    return value


def _optional_text(row: Row, field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    return value


def _parse_fragment(row: Row) -> Row:
    start, end = _range(row)
    return {
        "id": text(row, "id"),
        "paragraph": text(row, "paragraph"),
        "page": integer(row, "page", minimum=1),
        "layout_order": integer(row, "layout_order", minimum=0),
        "start": start,
        "end": end,
        "text": _position_text(row, start, end),
        "continues_to": _optional_text(row, "continues_to"),
    }


def _parse_note(row: Row) -> Row:
    start, end = _range(row)
    return {
        "id": text(row, "id"),
        "start": start,
        "end": end,
        "text": _position_text(row, start, end),
        "language": _optional_text(row, "language"),
    }


def _parse_citation(row: Row) -> Row:
    return {
        "id": text(row, "id"),
        "note": text(row, "note"),
        "anchor": text(row, "anchor"),
        "page": integer(row, "page", minimum=1),
        "layout_order": integer(row, "layout_order", minimum=0),
    }


def _parse_declaration(row: Row) -> Row:
    start, end = _range(row)
    level = text(row, "level")
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}")
    return {"id": text(row, "id"), "level": level, "start": start, "end": end,
            "language": text(row, "language")}


def _append_distinct(values: list, value) -> None:
    if value not in values:
        values.append(value)


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def _merge_nodes(fragments: list[Row]) -> list[Row]:
    """同一原文位置的重复导出合并为一个节点，保留全部导出标识与分歧取值。"""
    nodes: dict[tuple[int, int], Row] = {}
    for fragment in fragments:
        key = (fragment["start"], fragment["end"])
        node = nodes.setdefault(key, {
            "start": fragment["start"], "end": fragment["end"], "key": key,
            "exports": [], "texts": [], "paragraphs": [], "layouts": [], "targets": [],
        })
        node["exports"].append(fragment["id"])
        _append_distinct(node["texts"], fragment["text"])
        _append_distinct(node["paragraphs"], fragment["paragraph"])
        _append_distinct(node["layouts"], (fragment["page"], fragment["layout_order"]))
        if fragment["continues_to"] is not None:
            _append_distinct(node["targets"], fragment["continues_to"])
    ordered = [nodes[key] for key in sorted(nodes)]
    for previous, current in zip(ordered, ordered[1:]):
        if current["start"] < previous["end"]:
            raise ValueError("fragments overlap in original positions")
    for node in ordered:
        node["text"] = node["texts"][0] if len(node["texts"]) == 1 else None
        node["paragraph"] = node["paragraphs"][0] if len(node["paragraphs"]) == 1 else None
        node["page"], node["layout_order"] = min(node["layouts"])
        node["contradictory"] = (
            len(node["texts"]) > 1 or len(node["paragraphs"]) > 1 or len(node["layouts"]) > 1
        )
        node["loop"] = False
        node["broken_target"] = None
        node["successor"] = None
    return ordered


def _check_unit_overlap(nodes: list[Row], notes: list[Row]) -> None:
    spans = [(node["start"], node["end"]) for node in nodes]
    spans += [(note["start"], note["end"]) for note in notes]
    spans.sort()
    for previous, current in zip(spans, spans[1:]):
        if current[0] < previous[1]:
            raise ValueError("text units overlap in original positions")


def _build_continuation(nodes: list[Row], key_of_export: dict[str, tuple[int, int]],
                        disputes: list[Row]) -> None:
    """正文续接图：确认唯一无竞争的续接边，分叉、断引、回环记入争议。"""
    claimed: dict[tuple[int, int], tuple[int, int]] = {}
    for node in nodes:
        if len(node["targets"]) == 1:
            target = node["targets"][0]
            if target not in key_of_export:
                node["broken_target"] = target
                disputes.append({"type": "broken_continuation", "node": node, "target": target})
            else:
                claimed[node["key"]] = key_of_export[target]
        elif len(node["targets"]) > 1:
            disputes.append({"type": "fork", "node": node, "targets": list(node["targets"])})
    incoming: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for source, target in claimed.items():
        incoming.setdefault(target, []).append(source)
    confirmed: dict[tuple[int, int], tuple[int, int]] = {}
    for source, target in claimed.items():
        if len(incoming[target]) == 1:
            confirmed[source] = target
    for target, sources in incoming.items():
        if len(sources) > 1:
            disputes.append({"type": "fork", "target": target,
                             "predecessors": sorted(sources)})
    for node in nodes:
        key = node["key"]
        node["successor"] = confirmed.get(key)
        if key in confirmed:
            node["continuity"] = "confirmed"
        elif node["broken_target"] is not None:
            node["continuity"] = "broken"
        elif node["targets"]:
            node["continuity"] = "fork"
        else:
            node["continuity"] = "end"
    _mark_loops(nodes, confirmed, disputes)


def _mark_loops(nodes: list[Row], confirmed: dict, disputes: list[Row]) -> None:
    node_by_key = {node["key"]: node for node in nodes}
    seen: set[tuple[int, int]] = set()
    loops: list[list[tuple[int, int]]] = []
    for start in confirmed:
        if start in seen:
            continue
        path: list[tuple[int, int]] = []
        current: tuple[int, int] | None = start
        while current is not None and current not in seen:
            seen.add(current)
            path.append(current)
            current = confirmed.get(current)
        if current is not None and current in path:
            loops.append(path[path.index(current):])
    for cycle in loops:
        for key in cycle:
            node_by_key[key]["continuity"] = "loop"
            node_by_key[key]["loop"] = True
        disputes.append({"type": "loop", "members": sorted(cycle)})


def _build_chains(nodes: list[Row]) -> list[list[tuple[int, int]]]:
    """正文续接优先于页内排布：链内沿确认续接边，链间按链头页内排布。"""
    node_by_key = {node["key"]: node for node in nodes}
    confirmed = {node["key"]: node["successor"] for node in nodes
                 if node["successor"] is not None}
    has_predecessor = set(confirmed.values())
    chains: list[list[tuple[int, int]]] = []
    for node in nodes:
        if node["key"] in has_predecessor or node["loop"]:
            continue
        chain: list[tuple[int, int]] = []
        current: tuple[int, int] | None = node["key"]
        while current is not None and current not in chain:
            chain.append(current)
            current = confirmed.get(current)
        chains.append(chain)
    visited = {key for chain in chains for key in chain}
    loop_members = sorted((node for node in nodes if node["loop"]),
                          key=lambda node: (node["page"], node["layout_order"]))
    for node in loop_members:  # 回环没有链头，从页内排布最早的未访成员起沿边走完一圈
        if node["key"] in visited:
            continue
        chain = []
        current: tuple[int, int] | None = node["key"]
        while current is not None and current not in chain:
            chain.append(current)
            current = confirmed.get(current)
        chains.append(chain)
        visited.update(chain)
    chains.sort(key=lambda chain: (node_by_key[chain[0]]["page"],
                                   node_by_key[chain[0]]["layout_order"]))
    return chains


def _place_notes(notes: list[Row], citations: list[Row],
                 key_of_export: dict[str, tuple[int, int]],
                 disputes: list[Row]) -> dict[str, Row]:
    """共用边注在能够确认的首次引用处读一次；先后无法确认时保留候选位置。"""
    note_by_id = {note["id"]: note for note in notes}
    citations_by_note: dict[str, list[Row]] = {}
    for citation in citations:
        if citation["note"] not in note_by_id or citation["anchor"] not in key_of_export:
            disputes.append({"type": "broken_citation", "citation": citation})
            continue
        citations_by_note.setdefault(citation["note"], []).append(citation)
    placements: dict[str, Row] = {}
    for note in notes:
        found = citations_by_note.get(note["id"], [])
        if not found:
            placements[note["id"]] = {"note": note, "citations": [], "status": "no_citation"}
            continue
        first_layout = min((c["page"], c["layout_order"]) for c in found)
        firsts = [c for c in found if (c["page"], c["layout_order"]) == first_layout]
        confirmed = len(firsts) == 1
        if confirmed:
            anchor_key = key_of_export[firsts[0]["anchor"]]
            read_at: str | None = firsts[0]["id"]
            candidates: list[str] = []
        else:
            anchor_key = min(key_of_export[c["anchor"]] for c in firsts)
            read_at = None
            candidates = sorted(c["id"] for c in firsts)
            disputes.append({"type": "citation_order", "note": note,
                             "candidates": candidates})
        traced = [c["id"] for c in found if c["id"] != read_at and c["id"] not in candidates]
        placements[note["id"]] = {
            "note": note, "citations": [c["id"] for c in found],
            "read_at": read_at, "candidates": candidates, "traced_from": traced,
            "anchor": anchor_key, "sort_layout": first_layout,
            "position_confirmed": confirmed,
            "status": "confirmed" if confirmed else "to_verify",
        }
    return placements


def _resolve_tier(covering: list[Row], tier: str, reason: str) -> Row:
    languages = sorted({decl["language"] for decl in covering})
    if len(languages) == 1:
        return {"status": "confirmed", "language": languages[0], "source": tier,
                "declarations": sorted(decl["id"] for decl in covering)}
    return {"status": "to_verify", "language": None, "source": tier, "reason": reason,
            "claims": languages,
            "declarations": sorted(decl["id"] for decl in covering)}


def _signature(outcome: Row) -> tuple:
    return (outcome["status"], outcome["language"], outcome["source"],
            outcome.get("reason"), tuple(outcome.get("claims") or []),
            tuple(outcome["declarations"]))


def _resolve_ranges(ranges: list[tuple[int, int]], phrase: list[Row],
                    paragraph: list[Row], default: str) -> list[Row]:
    """词句声明优先于段落声明，其次文档默认语言；同层矛盾只让交叠文字待核。"""
    resolved: list[Row] = []
    for start, end in ranges:
        bounds = {start, end}
        for decl in phrase + paragraph:
            low, high = max(start, decl["start"]), min(end, decl["end"])
            if low < high:
                bounds.add(low)
                bounds.add(high)
        points = sorted(bounds)
        for low, high in zip(points, points[1:]):
            phrase_hits = [d for d in phrase if d["start"] <= low and d["end"] >= high]
            paragraph_hits = [d for d in paragraph if d["start"] <= low and d["end"] >= high]
            if phrase_hits:
                outcome = _resolve_tier(phrase_hits, "phrase", CONFLICT_PHRASE)
            elif paragraph_hits:
                outcome = _resolve_tier(paragraph_hits, "paragraph", CONFLICT_PARAGRAPH)
            else:
                outcome = {"status": "confirmed", "language": default,
                           "source": "document", "declarations": []}
            outcome["start"], outcome["end"] = low, high
            resolved.append(outcome)
    merged: list[Row] = []
    for outcome in resolved:
        if (merged and merged[-1]["end"] == outcome["start"]
                and _signature(merged[-1]) == _signature(outcome)):
            merged[-1]["end"] = outcome["end"]
        else:
            merged.append(outcome)
    return merged


def _slice_text(parts: list[Row], start: int, end: int) -> str | None:
    pieces = []
    for part in parts:
        low, high = max(start, part["start"]), min(end, part["end"])
        if low >= high:
            continue
        if part["text"] is None:
            return None
        pieces.append(part["text"][low - part["start"]:high - part["start"]])
    return "".join(pieces)


def _build_units(nodes: list[Row], notes: list[Row]) -> list[Row]:
    units: list[Row] = []
    paragraphs: dict[str, list[Row]] = {}
    for node in nodes:
        if node["paragraph"] is not None:
            paragraphs.setdefault(node["paragraph"], []).append(node)
    for name, members in paragraphs.items():
        members.sort(key=lambda n: n["start"])
        units.append({"kind": "paragraph", "id": name, "parts": members,
                      "ranges": [(n["start"], n["end"]) for n in members],
                      "pages": sorted({n["page"] for n in members})})
    for note in notes:
        units.append({"kind": "note", "id": note["id"], "parts": [note],
                      "ranges": [(note["start"], note["end"])], "pages": []})
    for node in nodes:
        if node["paragraph"] is None:
            units.append({"kind": "position", "id": f"{node['start']}-{node['end']}",
                          "parts": [node], "ranges": [node["key"]], "pages": []})
    return units


def _resolve_languages(units: list[Row], declarations: list[Row],
                       default: str) -> list[Row]:
    """按原文位置把声明归属到文字单元，再逐单元分层解析；返回悬空声明。"""
    dangling: list[Row] = []
    for unit in units:
        unit["phrase"], unit["paragraph_decls"], unit["unconfirmable"] = [], [], []
        if unit["kind"] == "note":
            note = unit["parts"][0]
            if note["language"] is not None:
                unit["paragraph_decls"].append({
                    "id": f"note:{note['id']}", "level": "paragraph",
                    "start": note["start"], "end": note["end"],
                    "language": note["language"]})
    for decl in declarations:
        hits = [unit for unit in units
                if any(_overlaps(decl["start"], decl["end"], start, end)
                       for start, end in unit["ranges"])]
        if not hits:
            dangling.append(decl)
        elif len(hits) > 1:
            for unit in hits:
                unit["unconfirmable"].append({"declaration": decl["id"],
                                              "reason": SPANS_UNITS,
                                              "start": decl["start"], "end": decl["end"],
                                              "language": decl["language"]})
        else:
            unit = hits[0]
            target = unit["phrase"] if decl["level"] == "phrase" else unit["paragraph_decls"]
            target.append(decl)
    for unit in units:
        if unit["kind"] == "position":
            unit["paragraph_decls"] = []  # 段落归属有争议时段落级声明不适用
        unit["resolved"] = _resolve_ranges(unit["ranges"], unit["phrase"],
                                           unit["paragraph_decls"], default)
    return dangling


def prepare(data: Row) -> Row:
    """校验并解析同一份导出，返回供三条数据链共用的模型。"""
    default = text(data, "document_language")
    fragments = _unique([_parse_fragment(row) for row in read_rows(data, "fragments")])
    notes = _unique([_parse_note(row) for row in _optional_rows(data, "margin_notes")])
    citations = _unique([_parse_citation(row) for row in _optional_rows(data, "citations")])
    declarations = _unique([_parse_declaration(row)
                            for row in _optional_rows(data, "language_declarations")])

    nodes = _merge_nodes(fragments)
    _check_unit_overlap(nodes, notes)
    key_of_export = {export: node["key"] for node in nodes for export in node["exports"]}
    node_by_key = {node["key"]: node for node in nodes}

    disputes: list[Row] = []
    for node in nodes:
        if node["contradictory"]:
            disputes.append({"type": "contradictory_exports", "node": node})
    _build_continuation(nodes, key_of_export, disputes)
    chains = _build_chains(nodes)
    placements = _place_notes(notes, citations, key_of_export, disputes)

    units = _build_units(nodes, notes)
    dangling = _resolve_languages(units, declarations, default)

    chain_of = {}
    for index, chain in enumerate(chains, start=1):
        for key in chain:
            chain_of[key] = index
    body_order = [key for chain in chains for key in chain]

    # 连续文本序列：正文链序为主，边注插到（候选）首次引用锚点之后。
    anchored: dict[tuple[int, int], list[Row]] = {}
    for placement in placements.values():
        if placement["status"] == "no_citation":
            continue
        anchored.setdefault(placement["anchor"], []).append(placement)
    for group in anchored.values():
        group.sort(key=lambda p: (p["sort_layout"], p["note"]["id"]))
    sequence: list[Row] = []
    for key in body_order:
        sequence.append({"kind": "body", "node": node_by_key[key]})
        for placement in anchored.get(key, []):
            sequence.append({"kind": "margin_note", "placement": placement})

    unit_of_node = {}
    for unit in units:
        for part in unit["parts"]:
            if "key" in part:
                unit_of_node[part["key"]] = unit
    predecessor_of = {}
    for node in nodes:
        if node["successor"] is not None:
            predecessor_of[node["successor"]] = node["key"]
    predecessor_candidates = {}
    for dispute in disputes:
        if dispute["type"] == "fork" and "target" in dispute:
            predecessor_candidates[dispute["target"]] = dispute["predecessors"]
    return {
        "default_language": default,
        "nodes": nodes,
        "node_by_key": node_by_key,
        "chains": chains,
        "chain_of": chain_of,
        "sequence": sequence,
        "notes": notes,
        "placements": placements,
        "disputes": disputes,
        "units": units,
        "unit_of_node": unit_of_node,
        "dangling_declarations": dangling,
        "predecessor_of": predecessor_of,
        "predecessor_candidates": predecessor_candidates,
    }


def language_intervals(unit: Row, start: int, end: int,
                       parts: list[Row] | None = None) -> list[Row]:
    """把单元解析结果裁剪到指定原文范围，附上覆盖文字。"""
    parts = parts if parts is not None else unit["parts"]
    intervals = []
    for outcome in unit["resolved"]:
        low, high = max(start, outcome["start"]), min(end, outcome["end"])
        if low >= high:
            continue
        interval = {"start": low, "end": high, "language": outcome["language"],
                    "source": outcome["source"], "status": outcome["status"],
                    "declarations": outcome["declarations"]}
        if outcome["status"] == "to_verify":
            interval["reason"] = outcome["reason"]
            interval["claims"] = outcome["claims"]
        interval["text"] = _slice_text(parts, low, high)
        intervals.append(interval)
    return intervals
