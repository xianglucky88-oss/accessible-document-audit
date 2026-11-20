# 文档无障碍证据审计

将带标签 PDF 的离线结构清单变为可逐对象复核的审计证据。输入是 PDF 导出器交付后的结构 JSON，包含页面和对象标识。

数据工程子方向为**其他（数据治理）**。基线接收已整理为 UTF-8 JSON 的合成业务数据，按数据链独立产出 JSON 事实。仓库根目录可直接运行，运行时和测试使用 Python 3.11 或以上的标准库。

## 运行

```sh
python3 -m accessible_document_audit reading-order examples/reading-order.json
python3 -m accessible_document_audit reading-order examples/reading-order.json --sqlite facts.sqlite
python3 -m unittest discover -s tests -v
```

Python 调用入口为 `process(pipeline, data)`。命令行也可以将 JSON 结果输出到标准输出。选用 SQLite 时，`runs` 保留原始 JSON 及 SHA-256，`facts` 保留每项具名事实和对应批次。每个输入按规范化 JSON 的摘要标识，同一处理链重复导入同一输入只保留一批；输入或处理失败时不会留下半批结果。处理逻辑改版后的重算应使用独立结果库。

## 数据链与离线样本

| 数据链 | 基线行为 | 试样 |
|---|---|---|
| `reading-order` | 按单页结构标签提供的次序生成朗读对象序列。 | `examples/reading-order.json` |
| `table-headers` | 按显式关联解析单个数据格引用的表头对象。 | `examples/table-headers.json` |
| `form-controls` | 识别缺少显式辅助技术标签的可交互字段。 | `examples/form-controls.json` |
| `image-alternatives` | 按图形对象记录显式替代说明及其缺失情况。 | `examples/image-alternatives.json` |
| `text-language` | 在忽略嵌套覆盖的扁平节点上读取节点语言或文档默认语言。 | `examples/text-language.json` |
| `narration-text` | 按确认的正文续接组织朗读序列，边注在首次确认引用处插入并保留自身语言，各段附语言区间与待核标记。 | `examples/narration-text.json` |
| `narration-reading-order` | 合并同一原文位置的重复导出，指出矛盾导出、续接分叉、断引、回环与引用先后无法确认的争议关系。 | `examples/narration-reading-order.json` |
| `narration-language` | 按原文起止位置把词句/段落语言声明解析成逐段语言区间，列出实际声明与无法确认的原因。 | `examples/narration-language.json` |

活动口径来自各样本。样例记录的业务标识用作事实键或保留在结果中。`tests/expected` 中的结果只描述这些基线试样。合成数据和示例规则用于开发验证，实际签发、专业判定及合规认证需采用对应项目的正式数据与规则。

## 有声版朗读方案

`narration-*` 三条数据链读取同一份导出（正文续接、边注引用、段落归属、语言声明），三份结果都带原文起止位置，可按位置互相查证：

- 语言声明只有原文起止位置，层级为词句（phrase）或段落（paragraph）；词句优先于段落，其次文档默认语言。同一层级相互矛盾的声明只让交叠文字待核，其余部分照常解析。
- 跨页段落按续接关系接合后，局部声明仍只管原来的文字范围；边注插到正文引用处时保留边注自己的语言。
- 正文续接优先于页内排布；共用边注在能够确认的首次引用处读一次，其余引用仍可追到它；引用先后无法确认时保留候选位置，不按导出顺序任选。
- 同一原文位置的重复导出合并，文字相同但位置不同仍保留；同位置矛盾导出、续接分叉、断引、回环记入读序明细的争议事实，连续文本只保留仍能确认的先后与语言区间。
- 读序不明不抹掉已确认的语言，语言待核也不丢掉仍可接续的正文；连续文本中 `continuity` 为 `confirmed`/`end` 时可继续读，`fork`/`broken`/`loop` 或任何 `to_verify` 标记都需回查原稿。
