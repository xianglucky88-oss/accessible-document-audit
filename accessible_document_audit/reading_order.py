"""按单页结构标签提供的次序生成朗读对象序列。"""

from .contract import Row, apply_rows, integer, text


def build_facts(data: Row) -> list[Row]:
    def describe(row: Row) -> Row:
        return {"page": integer(row, "page", minimum=1), "order": integer(row, "tag_order"),
                "role": text(row, "role"), "text": text(row, "text")}

    facts = apply_rows(data, describe)
    citations = {(row["page"], row["order"]) for row in facts}
    if len(citations) != len(facts):
        raise ValueError("duplicate tag order on the same page")
    return sorted(facts, key=lambda row: (row["page"], row["order"]))
