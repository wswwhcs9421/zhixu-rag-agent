# 企业制度文档切分：公开案例与规则扩展

快照日期：2026-11-02。目标是让一份制度中混合的不同结构分别参与切分，避免只适配“第几条”。这些文件用于解析研究与回归测试，**没有上传到实际知识库，也不代表本公司的制度**。

## 阅读过的公开企业原文

| 案例 | 已确认的结构特征 |
| --- | --- |
| [GitLab 全球差旅与报销政策](https://handbook.gitlab.com/handbook/finance/expenses/) | 多级数字标题，例如 `4.3 Missing Receipt Affidavit`；类别、清单与例外 |
| [GitLab 采购制度与流程](https://handbook.gitlab.com/handbook/finance/procurement/) | `1.`、`2.A.` 等混合编号；采购生命周期、审查步骤 |
| [GitLab Coupa FAQ](https://handbook.gitlab.com/handbook/finance/procurement/coupa-faq/) | 独立的问题标题与回答，例如 `How do suppliers register for the CSP?` |
| [GitLab Navan 报销操作指南](https://handbook.gitlab.com/handbook/business-technology/enterprise-applications/guides/navan-expense-guide/) | 多级功能标题、操作步骤和项目列表 |
| [GitLab 休假政策](https://handbook.gitlab.com/handbook/people-group/time-off-and-absence/leave-types/) | 资格、申请、待遇、返岗等分节，含条件与例外 |
| [GitLab 福利政策](https://handbook.gitlab.com/handbook/total-rewards/benefits/) | 栏目标题与项目列表 |
| [37signals / Basecamp 福利手册](https://basecamp.com/handbook/benefits-and-perks) | 保险、休假、费用等独立主题与普通叙述 |
| [37signals / Basecamp 工作方式手册](https://basecamp.com/handbook/how-we-work) | 主题标题和连续叙述，没有“第几条” |

已保存 8 份原文快照至 `public_sources/`，下载地址、转换说明和 SHA256 见 `sources.json`。GitLab 使用其公开仓库的 Markdown；Basecamp 从网页主内容转换为 Markdown并去除导航。回归测试还会移除部分 Markdown 标记，模拟同一资料以普通文本导出的情况。

原有财政部 10 份企业内控指引也继续参与回归，检查 175 条完整条文与 68 处标准答案证据没有丢失。

## 新规则如何配合

1. 先识别文档名称、章/节/条、标题与编号层级。数字层级结合相邻编号判断；日期、金额、孤立版本号、目录点线不直接作为章节。
2. 将完整条款、短问答、短流程或清单作为优先保留的单元。条款内部的小标题与分项不会机械变成独立片段。
3. 长单元内部进一步识别段落、列表条目、步骤、表格及代码块。优先在这些块之间分组。
4. 表格太长时重复表头和简短注释，按完整行分组。单个超长单元格改为带行标识与列名的文本片段，保留字段值。
5. 长答案延续问题；长条件清单延续原文引导语。续片段复用的文字来自原文，不自动概括或编写制度。
6. 最后才使用句子边界和字符长度兜底。字符上限仍为 1000，重叠上限仍为 120，但上下文复用会占用长度预算，并非每片都恰好 1000 字。

章节路径保留在现有“查看片段”界面中。可以在同一份混合文档中同时使用编号、问答和表格规则，不必为每种资料手动修改 LLM 提示词。

## 合成边界场景

`tests/test_chunking_patterns.py` 中的中文公司名称、表格金额和流程均为**明确标记的合成测试数据**，只检查切分行为，不冒充任何公司的真实制度。

覆盖中文层级、数字/字母编号、普通栏目、无标记文档名称、独立问题、Q/A、加粗和 Setext 标题、短/长操作流程、条件清单、Markdown/制表符表格、空单元格、转义竖线、超长单元格、代码围栏，以及日期/金额/版本/目录的误识别防护。

`切分预览.md` 展示若干真实原文与合成场景的实际输出，方便人工复核。`validation_report.json` 记录快照、片段数量、长度与文本保留核验；`test_results.xml` 是运行下面的命令后生成的测试输出，不随发布版附带。这些都不是问答命中率。

## 复现

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe evaluation\chunking_examples\collect_sources.py
.\.venv\Scripts\python.exe evaluation\chunking_examples\preview.py
.\.venv\Scripts\python.exe -m pytest --junitxml=evaluation/chunking_examples/test_results.xml
```

已有公开快照时采集脚本直接使用本地文件；缺失时重新下载，更新后的网页可能与本次快照不同，因此比较实验应固定现有 SHA256。

## 实际边界

当前应用仍支持 PDF、TXT、Markdown，不新增 Word、Excel 或网页直接上传。这里的网页转换仅用于收集研究样本。扫描件、图片流程图、复杂或合并单元格表格仍需要专门的 OCR/版面解析；结构信号缺失时采用通用文本切分。超长问题、表头、注释等不能无限重复，极端情形需要查看片段并人工调整。

更换切分规则并不自动证明检索效果提升。应使用固定问题集分别统计证据命中和最终回答正确率，再决定参数是否合适。
