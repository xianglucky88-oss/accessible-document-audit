"""在忽略嵌套覆盖的扁平节点上读取节点语言或文档默认语言。"""

from .contract import Row, apply_rows, text


def build_facts(data: Row) -> list[Row]:
    default = text(data, "document_language")

    def resolve(row: Row) -> Row:
        explicit = "language" in row
        return {"language": text(row, "language") if explicit else default,
                "source": "explicit" if explicit else "document"}

    return apply_rows(data, resolve)
