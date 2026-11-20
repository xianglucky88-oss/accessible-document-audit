"""按发布语言和出现位置核对每处图可读到的必要路线信息。

材料把每处图的用途（正文指路还是章节装饰）、所引用的文字说明
（``description_ids``）和必须传达的路线项（``required_items``）分开登记。
说明由若干文字段组成，也可以再引用其他说明；可读的路线项是各文字段
``covers`` 的并集。核对按（图, 发布语言）逐项进行：

* 只覆盖部分必要项的说明不能证明整张图已能替代，缺项列入 ``missing_items``。
* 一节说明可由多段文字共同提供；也允许一段说明被多幅图引用。
* 某一语言缺少译文时，不能沿用另一语言的完成状态；缺译文列入
  ``missing_translations``，同时保留该说明下仍可确认的部分。
* 说明上的 ``corrections`` 表示该段文字已更正某个路线项，仍引用它的图需要
  补充说明；必要项与更正值无关的图保持已核验。
* 嵌套引用成环或指向不存在的内容时，保留其余可确认的覆盖，并把缺口
  （``cycle`` / ``text`` / ``description``）登记到 ``unresolved_references``，
  便于编辑处理未通过的位置。
"""

from __future__ import annotations

from .contract import Row, index_rows, integer, read_rows, text, text_list

PURPOSES = {"wayfinding", "decoration"}
PLACEMENTS = {"body", "chapter-decoration"}


def _gap(kind: str, identifier: str, through: str | None) -> Row:
    return {"kind": kind, "id": identifier, "through": through}


def _unique_gaps(gaps: list[Row]) -> list[Row]:
    unique = {(row["kind"], row["id"], row["through"] or ""): row for row in gaps}
    return [unique[key] for key in sorted(unique)]


def _unique_translations(rows: list[Row]) -> list[Row]:
    unique = {(row["description"], row["language"], row["through"] or ""): row for row in rows}
    return [unique[key] for key in sorted(unique)]


def _empty() -> Row:
    return {"items": set(), "corrections": set(), "gaps": [], "translations": []}


class Material:
    """校验并索引文字段、说明及其译文关系。"""

    def __init__(self, data: Row) -> None:
        self.text_language: dict[str, str] = {}
        self.text_covers: dict[str, list[str]] = {}
        for key, row in index_rows(read_rows(data, "texts"), "id").items():
            text(row, "content")
            self.text_language[key] = text(row, "language")
            self.text_covers[key] = text_list(row, "covers", default=[])

        self.language: dict[str, str] = {}
        self.texts: dict[str, list[str]] = {}
        self.includes: dict[str, list[str]] = {}
        self.corrections: dict[str, list[str]] = {}
        self.source_of: dict[str, str] = {}
        self.translations: dict[tuple[str, str], str] = {}
        for key, row in index_rows(read_rows(data, "descriptions"), "id").items():
            language = text(row, "language")
            text_ids = text_list(row, "text_ids", default=[])
            for text_id in text_ids:
                known = self.text_language.get(text_id)
                if known is not None and known != language:
                    raise ValueError(f"text {text_id} does not match description {key} language")
            self.language[key] = language
            self.texts[key] = text_ids
            self.includes[key] = text_list(row, "includes", default=[])
            self.corrections[key] = text_list(row, "corrections", default=[])
            if "translation_of" in row:
                source = text(row, "translation_of")
                if source == key:
                    raise ValueError(f"description {key} cannot translate itself")
                slot = (source, language)
                if slot in self.translations:
                    raise ValueError(f"duplicate {language} translation for description {source}")
                self.translations[slot] = key
                self.source_of[key] = source

        for (source, language), target in self.translations.items():
            if source in self.language and self.language[source] == language:
                raise ValueError(f"description {target} must be in a language other than {source}")
            walk, current = {target}, source
            while current in self.source_of:
                if current in walk:
                    raise ValueError(f"translation cycle at description {target}")
                walk.add(current)
                current = self.source_of[current]

    def resolve(self, description_id: str, language: str, stack: tuple[str, ...] = ()) -> Row:
        """汇总说明在指定语言下可确认的路线项，并记录译文和嵌套引用缺口。"""
        result = _empty()
        if description_id in stack:
            result["gaps"].append(_gap("cycle", description_id, stack[-1]))
            return result
        if self.language[description_id] != language:
            translation = self.translations.get((description_id, language))
            if translation is not None:
                result = self.resolve(translation, language, stack + (description_id,))
                # 译文与原文内容相同，原文声明的更正同样适用。
                result["corrections"].update(self.corrections[description_id])
                return result
            # 缺译文的说明不能借用原文的完成状态，但其嵌套说明仍可能有该语言版本。
            if self.texts[description_id]:
                result["translations"].append(
                    {"description": description_id, "language": language,
                     "through": stack[-1] if stack else None})
            self._merge(result, self._children(description_id, language, stack))
            return result

        result["items"].update(self._own_items(description_id, result["gaps"]))
        result["corrections"].update(self.corrections[description_id])
        self._merge(result, self._children(description_id, language, stack))
        return result

    def _own_items(self, description_id: str, gaps: list[Row]) -> set[str]:
        items: set[str] = set()
        for text_id in self.texts[description_id]:
            if text_id in self.text_covers:
                items.update(self.text_covers[text_id])
            else:
                gaps.append(_gap("text", text_id, description_id))
        return items

    def _children(self, description_id: str, language: str, stack: tuple[str, ...]) -> Row:
        result = _empty()
        for included in self.includes[description_id]:
            if included not in self.language:
                result["gaps"].append(_gap("description", included, description_id))
                continue
            self._merge(result, self.resolve(included, language, stack + (description_id,)))
        return result

    @staticmethod
    def _merge(target: Row, child: Row) -> None:
        target["items"].update(child["items"])
        target["corrections"].update(child["corrections"])
        target["gaps"].extend(child["gaps"])
        target["translations"].extend(child["translations"])


def _inspect(material: Material, key: str, row: Row, published: list[str]) -> list[Row]:
    purpose = text(row, "purpose")
    if purpose not in PURPOSES:
        raise ValueError(f"{key}: purpose must be one of {sorted(PURPOSES)}")
    placement = text(row, "placement")
    if placement not in PLACEMENTS:
        raise ValueError(f"{key}: placement must be one of {sorted(PLACEMENTS)}")
    required = text_list(row, "required_items", default=[])
    if purpose == "wayfinding" and not required:
        raise ValueError(f"{key}: wayfinding figure must declare required_items")
    if purpose == "decoration" and required:
        raise ValueError(f"{key}: decoration figure must not require route information")
    cited = text_list(row, "description_ids", default=[])
    languages = text_list(row, "published_languages", default=published)
    if not languages:
        raise ValueError(f"{key}: published_languages must not be empty")
    page = integer(row, "page", minimum=1)
    obj = text(row, "object")

    facts = []
    for language in languages:
        readable: set[str] = set()
        corrected: set[str] = set()
        gaps: list[Row] = []
        translations: list[Row] = []
        for description_id in cited:
            if description_id not in material.language:
                gaps.append(_gap("description", description_id, None))
                continue
            resolved = material.resolve(description_id, language)
            # 已更正的路线项不能算作可读：该说明里的文字不再反映当前出口。
            readable.update(resolved["items"] - resolved["corrections"])
            corrected.update(resolved["corrections"])
            gaps.extend(resolved["gaps"])
            translations.extend(resolved["translations"])

        missing = [item for item in required if item not in readable]
        gaps = _unique_gaps(gaps)
        translations = _unique_translations(translations)
        # 装饰用的裁切图不承担指路职责：材料缺口照常列出，但不影响是否已核验。
        passed = not missing and (purpose != "wayfinding" or not gaps and not translations)
        facts.append({
            "fact_id": f"{key}@{language}",
            "page": page,
            "object": obj,
            "purpose": purpose,
            "placement": placement,
            "language": language,
            "description_ids": cited,
            "required_items": required,
            "covered_items": [item for item in required if item in readable],
            "missing_items": missing,
            "corrected_items": [item for item in required if item in corrected],
            "unresolved_references": gaps,
            "missing_translations": translations,
            "status": "verified" if passed else "needs_supplement",
        })
    return facts


def build_facts(data: Row) -> list[Row]:
    published = text_list(data, "published_languages")
    material = Material(data)
    facts = []
    for key, row in index_rows(read_rows(data, "records"), "id").items():
        facts.extend(_inspect(material, key, row, published))
    return sorted(facts, key=lambda row: (row["language"], row["placement"],
                                          row["page"], row["fact_id"]))
