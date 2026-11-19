"""按图形对象记录显式替代说明及其缺失情况。"""

from .contract import Row, apply_rows, integer, text


def build_facts(data: Row) -> list[Row]:
    def inspect(row: Row) -> Row:
        alternative = row.get("alternate_text", "")
        if not isinstance(alternative, str):
            raise ValueError("alternate_text must be text")
        return {"page": integer(row, "page", minimum=1), "object": text(row, "object"),
                "alternate_text": alternative.strip(), "has_alternative": bool(alternative.strip())}

    return apply_rows(data, inspect)
