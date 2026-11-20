"""核验导航入口经页码、旧别名与转跳声明后最终到达的章节及语言覆盖。

输入数据包含三部分：

* ``structure``：正文结构导出。每个章节给出当前页码、发布语言以及保留的
  旧别名。同一页码可以承载多个章节、同一旧别名也可能被多个章节声明，这两
  种结构性歧义都作为核验结果保留，而不是静默选取其一。
* ``entries`` 与 ``redirects``：导航入口及其目标声明。入口目标是一个引用
  （``page`` / ``alias`` / ``chapter``）；转跳声明把一个引用继续指向另一个
  引用，因此解析过程可能形成多跳链路甚至回到已走过目标的环。
* ``requirements``：各发布语言必须到达的章节清单。译本在显式许可
  （``source_target_allowed``）下可以落到原文语言章节，实际到达语言单列。
"""

from __future__ import annotations

from .contract import Row, integer, text

REF_KINDS = ("page", "alias", "chapter")
RESOLVED = "resolved"
AMBIGUOUS = "ambiguous"
UNRESOLVED = "unresolved"
CYCLE = "cycle"


def _ref(row: Row, field: str) -> tuple[str, object]:
    ref = row[field]
    if not isinstance(ref, dict):
        raise ValueError(f"{field} must be a target reference object")
    kind = ref.get("kind")
    if kind not in REF_KINDS:
        raise ValueError(f"{field}.kind must be one of {', '.join(REF_KINDS)}")
    value = ref.get("value")
    if kind == "page":
        if type(value) is not int or value < 1:
            raise ValueError(f"{field}.value must be a positive page number")
    elif not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}.value must be nonempty text")
    else:
        value = value.strip()
    return kind, value


def _ref_json(ref: tuple[str, object]) -> Row:
    return {"kind": ref[0], "value": ref[1]}


def _ref_key(ref: tuple[str, object]) -> str:
    return f"{ref[0]}:{ref[1]}"


def _canonical_cycle(cycle: tuple[tuple[str, object], ...]) -> tuple[tuple[str, object], ...]:
    """把同一环的不同起点（含回到起点的闭合重复）规范化为字典序最小旋转。"""
    if len(cycle) > 1 and cycle[0] == cycle[-1]:
        cycle = cycle[:-1]
    rotations = [tuple(cycle[i:] + cycle[:i]) for i in range(len(cycle))]
    return min(rotations, key=lambda rotation: tuple(_ref_key(ref) for ref in rotation))


def _chapter_brief(chapter: Row) -> Row:
    return {"id": chapter["id"], "title": chapter["title"],
            "language": chapter["language"], "page": chapter["page"]}


def _resolve(ref, redirects, page_index, alias_index, chapters, seen, path):
    """沿转跳声明解析单个引用，返回 resolved/ambiguous/unresolved/cycle。"""
    if ref in seen:
        return {"status": CYCLE, "cycle_refs": path[seen[ref]:] + [ref], "path": path + [ref]}
    seen = {**seen, ref: len(path)}
    path = path + [ref]

    if ref in redirects:
        branches = [
            _resolve(target, redirects, page_index, alias_index, chapters, seen, path)
            for target in redirects[ref]
        ]
        return _merge_branches(branches, path)

    kind, value = ref
    if kind == "chapter":
        hits = [value] if value in chapters else []
        unknown_issue = "unknown-chapter"
    elif kind == "page":
        hits = list(page_index.get(value, ()))
        unknown_issue = "unknown-page"
    else:
        hits = list(alias_index.get(value, ()))
        unknown_issue = "unknown-alias"

    if len(hits) == 1:
        return {"status": RESOLVED, "chapter": hits[0], "matched_by": kind, "path": path}
    if not hits:
        return {"status": UNRESOLVED, "issue": unknown_issue, "path": path}
    return {"status": AMBIGUOUS, "issue": f"ambiguous-{kind}",
            "candidates": sorted(hits), "path": path}


def _merge_branches(branches, path):
    """合并同一引用上多条转跳声明的解析结果。"""
    for branch in branches:
        if branch["status"] == CYCLE:
            return branch
    candidates = set()
    for branch in branches:
        if branch["status"] == RESOLVED:
            candidates.add(branch["chapter"])
        elif branch["status"] == AMBIGUOUS:
            candidates.update(branch["candidates"])
    if len(candidates) > 1:
        deepest = max(branches, key=lambda branch: len(branch["path"]))
        return {"status": AMBIGUOUS, "issue": "ambiguous-declaration",
                "candidates": sorted(candidates), "path": deepest["path"]}
    if len(candidates) == 1 and all(branch["status"] != UNRESOLVED for branch in branches):
        deepest = max(branches, key=lambda branch: len(branch["path"]))
        return {"status": RESOLVED, "chapter": next(iter(candidates)),
                "matched_by": deepest["matched_by"], "path": deepest["path"]}
    for branch in branches:
        if branch["status"] == UNRESOLVED:
            return {"status": UNRESOLVED, "issue": branch["issue"], "path": branch["path"]}
    return branches[0]


def build_facts(data: Row) -> list[Row]:
    structure = data["structure"]
    if not isinstance(structure, list) or any(not isinstance(row, dict) for row in structure):
        raise ValueError("structure must contain JSON objects")
    entries = data["entries"]
    if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
        raise ValueError("entries must contain JSON objects")
    redirect_rows = data.get("redirects", [])
    if not isinstance(redirect_rows, list) or any(not isinstance(row, dict) for row in redirect_rows):
        raise ValueError("redirects must contain JSON objects")
    requirements = data["requirements"]
    if not isinstance(requirements, list) or any(not isinstance(row, dict) for row in requirements):
        raise ValueError("requirements must contain JSON objects")

    chapters: dict[str, Row] = {}
    page_index: dict[int, list[str]] = {}
    alias_index: dict[str, list[str]] = {}
    for row in structure:
        chapter_id = text(row, "id")
        if chapter_id in chapters:
            raise ValueError(f"duplicate chapter id: {chapter_id}")
        chapter = {
            "id": chapter_id,
            "title": text(row, "title"),
            "language": text(row, "language"),
            "page": integer(row, "page", minimum=1),
        }
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise ValueError("aliases must contain nonempty text")
        chapter["aliases"] = sorted({alias.strip() for alias in aliases})
        chapters[chapter_id] = chapter
        page_index.setdefault(chapter["page"], []).append(chapter_id)
        for alias in chapter["aliases"]:
            alias_index.setdefault(alias, []).append(chapter_id)

    redirects: dict[tuple[str, object], list[tuple[str, object]]] = {}
    for row in redirect_rows:
        source = _ref(row, "from")
        target = _ref(row, "to")
        redirects.setdefault(source, [])
        if target not in redirects[source]:
            redirects[source].append(target)

    parsed_entries = []
    seen_entry_ids: set[str] = set()
    for row in entries:
        entry_id = text(row, "id")
        if entry_id in seen_entry_ids:
            raise ValueError(f"duplicate entry id: {entry_id}")
        seen_entry_ids.add(entry_id)
        parsed_entries.append({
            "id": entry_id,
            "location": text(row, "location"),
            "language": text(row, "language"),
            "target": _ref(row, "target"),
        })

    req_by_language: dict[str, Row] = {}
    for row in requirements:
        language = text(row, "language")
        if language in req_by_language:
            raise ValueError(f"duplicate requirement language: {language}")
        native = _chapter_list(row, "chapters", chapters)
        allowed = row.get("source_target_allowed", False)
        if type(allowed) is not bool:
            raise ValueError("source_target_allowed must be true or false")
        source_language = row.get("source_language")
        if source_language is not None and not isinstance(source_language, str):
            raise ValueError("source_language must be text")
        source_chapters = _chapter_list(row, "source_chapters", chapters, required=False)
        if source_chapters and not allowed:
            raise ValueError(f"source chapters require source_target_allowed for {language}")
        if source_chapters and not source_language:
            raise ValueError(f"source chapters require source_language for {language}")
        req_by_language[language] = {
            "language": language,
            "chapters": native,
            "source_chapters": source_chapters,
            "source_language": source_language,
            "source_target_allowed": allowed,
        }

    unknown_languages = sorted({entry["language"] for entry in parsed_entries} - set(req_by_language))
    if unknown_languages:
        raise ValueError(f"entries use languages without requirements: {', '.join(unknown_languages)}")

    facts: list[Row] = []
    walked: dict[str, set[tuple[str, object]]] = {}
    cycle_refs: dict[tuple[tuple[str, object], ...], set[str]] = {}
    # 章节覆盖台账：语言 -> 章节 -> 入口分类
    reachable: dict[str, dict[str, list[str]]] = {}
    attempting: dict[str, dict[str, list[str]]] = {}

    for entry in parsed_entries:
        result = _resolve(entry["target"], redirects, page_index, alias_index,
                          chapters, seen={}, path=[])
        walked[entry["id"]] = set(result["path"])
        path = [_ref_json(ref) for ref in result["path"]]
        fact: Row = {
            "fact_id": f"entry:{entry['id']}",
            "entry_id": entry["id"],
            "location": entry["location"],
            "language": entry["language"],
            "declared_target": _ref_json(entry["target"]),
            "resolution_path": path,
            "status": result["status"],
            "final_chapter": None,
            "matched_by": None,
            "arrival_language": None,
            "requirement_result": "unreachable",
            "issue": None,
            "candidates": [],
            "cycle_refs": [],
        }
        requirement = req_by_language[entry["language"]]

        if result["status"] == RESOLVED:
            chapter = chapters[result["chapter"]]
            fact["final_chapter"] = chapter["id"]
            fact["matched_by"] = result["matched_by"]
            fact["arrival_language"] = chapter["language"]
            fact["requirement_result"], fact["issue"] = _check_requirement(chapter, requirement)
            if fact["requirement_result"] in ("required", "source-fallback"):
                reachable.setdefault(entry["language"], {}).setdefault(chapter["id"], []).append(entry["id"])
        elif result["status"] == AMBIGUOUS:
            fact["issue"] = result["issue"]
            fact["candidates"] = [_chapter_brief(chapters[cid]) for cid in result["candidates"]]
            for cid in result["candidates"]:
                attempting.setdefault(entry["language"], {}).setdefault(cid, []).append(entry["id"])
        elif result["status"] == CYCLE:
            fact["issue"] = "redirect-cycle"
            canonical = _canonical_cycle(tuple(result["cycle_refs"]))
            fact["cycle_refs"] = [_ref_json(ref) for ref in canonical]
            cycle_refs.setdefault(canonical, set()).add(entry["id"])
        else:
            fact["issue"] = result["issue"]
        facts.append(fact)

    facts.extend(_structural_ambiguity_facts(page_index, alias_index, parsed_entries, walked, chapters))
    facts.extend(_redirect_cycle_facts(redirects, page_index, alias_index, chapters, cycle_refs))
    facts.extend(_coverage_facts(req_by_language, chapters, reachable, attempting))
    return sorted(facts, key=lambda fact: fact["fact_id"])


def _chapter_list(row: Row, field: str, chapters: dict[str, Row], *, required: bool = True) -> list[str]:
    if field not in row:
        if required:
            raise ValueError(f"{field} is required")
        return []
    values = row[field]
    if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{field} must contain chapter ids")
    values = [value.strip() for value in values]
    unknown = sorted(set(values) - set(chapters))
    if unknown:
        raise ValueError(f"unknown chapter in {field}: {', '.join(unknown)}")
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate chapter in {field}")
    return values


def _check_requirement(chapter: Row, requirement: Row) -> tuple[str, str | None]:
    cid = chapter["id"]
    if cid in requirement["chapters"]:
        if chapter["language"] == requirement["language"]:
            return "required", None
        return "not-required", "language-mismatch"
    if cid in requirement["source_chapters"]:
        if requirement["source_target_allowed"] and chapter["language"] == requirement["source_language"]:
            return "source-fallback", None
        return "not-required", "source-target-not-allowed"
    if chapter["language"] != requirement["language"] and not requirement["source_target_allowed"]:
        return "not-required", "source-target-not-allowed"
    return "not-required", "target-not-required"


def _structural_ambiguity_facts(page_index, alias_index, entries, walked, chapters) -> list[Row]:
    hits: dict[tuple[str, object], list[str]] = {}
    for page, ids in page_index.items():
        if len(ids) > 1:
            hits[("page", page)] = sorted(ids)
    for alias, ids in alias_index.items():
        if len(ids) > 1:
            hits[("alias", alias)] = sorted(ids)
    facts = []
    for ref, candidate_ids in sorted(hits.items(), key=lambda item: _ref_key(item[0])):
        affected = sorted(
            entry["id"] for entry in entries
            if ref in walked.get(entry["id"], set())
        )
        facts.append({
            "fact_id": f"ambiguity:{_ref_key(ref)}",
            "issue": f"ambiguous-{ref[0]}",
            "ref": _ref_json(ref),
            "candidates": [_chapter_brief(chapters[cid]) for cid in candidate_ids],
            "entries": affected,
        })
    return facts


def _redirect_cycle_facts(redirects, page_index, alias_index, chapters, cycle_refs) -> list[Row]:
    for source in redirects:
        result = _resolve(source, redirects, page_index, alias_index, chapters, seen={}, path=[])
        if result["status"] == CYCLE:
            cycle_refs.setdefault(_canonical_cycle(tuple(result["cycle_refs"])), set())
    facts = []
    for cycle, entry_ids in sorted(cycle_refs.items(), key=lambda item: tuple(_ref_key(ref) for ref in item[0])):
        facts.append({
            "fact_id": "cycle:" + "->".join(_ref_key(ref) for ref in cycle),
            "issue": "redirect-cycle",
            "cycle_refs": [_ref_json(ref) for ref in cycle + (cycle[0],)],
            "entries": sorted(entry_ids),
        })
    return facts


def _coverage_facts(req_by_language, chapters, reachable, attempting) -> list[Row]:
    facts = []
    for language in sorted(req_by_language):
        requirement = req_by_language[language]
        targets = [("native", cid) for cid in requirement["chapters"]]
        targets += [("source-fallback", cid) for cid in requirement["source_chapters"]]
        for kind, cid in targets:
            entries_here = sorted(reachable.get(language, {}).get(cid, []))
            attempting_here = sorted(attempting.get(language, {}).get(cid, []))
            facts.append({
                "fact_id": f"coverage:{language}:{cid}",
                "language": language,
                "chapter": cid,
                "chapter_title": chapters[cid]["title"],
                "target_kind": kind,
                "reachable": bool(entries_here),
                "entries": entries_here,
                "attempting_entries": attempting_here,
                "arrival_language": chapters[cid]["language"],
            })
    return facts
