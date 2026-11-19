"""识别缺少显式辅助技术标签的可交互字段。"""

from .contract import Row, apply_rows, integer, text


def build_facts(data: Row) -> list[Row]:
    def describe(row: Row) -> Row:
        label = row.get("accessible_label", "")
        if not isinstance(label, str):
            raise ValueError("accessible_label must be text")
        return {"page": integer(row, "page", minimum=1), "role": text(row, "role"),
                "accessible_label": label.strip(), "missing_label": not label.strip()}

    return apply_rows(data, describe)
