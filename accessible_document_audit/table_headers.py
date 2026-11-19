"""按显式关联解析单个数据格引用的表头对象。"""

from .contract import Row, apply_rows, index_rows, read_rows, text


def build_facts(data: Row) -> list[Row]:
    headers = index_rows(read_rows(data, "headers"), "id")

    def describe(row: Row) -> Row:
        table = text(row, "table")
        refs = row["header_ids"]
        if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref for ref in refs):
            raise ValueError("header_ids must contain header IDs")
        labels, missing = [], []
        for ref in dict.fromkeys(refs):
            header = headers.get(ref)
            if header is None or text(header, "table") != table:
                missing.append(ref)
            else:
                labels.append({"id": ref, "text": text(header, "label")})
        return {"table": table, "headers": labels, "unresolved_headers": missing}

    return apply_rows(data, describe)
