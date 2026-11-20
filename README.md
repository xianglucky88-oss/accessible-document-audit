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
| `navigation-links` | 沿页码、旧别名与转跳声明解析导航入口最终落章，核验语言必达章节覆盖。 | `examples/navigation-links.json` |

活动口径来自各样本。样例记录的业务标识用作事实键或保留在结果中。`tests/expected` 中的结果只描述这些基线试样。合成数据和示例规则用于开发验证，实际签发、专业判定及合规认证需采用对应项目的正式数据与规则。
