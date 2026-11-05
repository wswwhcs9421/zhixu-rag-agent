# 第三方资料与许可说明

原创应用代码采用 [MIT 许可证](LICENSE)。许可证沿用 GitHub 仓库已有的版权声明；下述第三方资料不因应用代码采用 MIT 而改变原有权利或许可。

## 测试资料

`evaluation/enterprise_v1/` 的资料来源于中华人民共和国财政部公开发布的《企业内部控制应用指引》（2010 年文本）。官方发布页、原 PDF、SHA256 和抽取范围见该目录的 `README.md` 与 `sources.json`。题目是基于这些固定资料编写的业务问法，不是企业生产用户日志。

`evaluation/chunking_examples/public_sources/` 保留用于离线回归的 GitLab 与 37signals / Basecamp 公开手册文本快照。原作者、下载地址、快照时间、转换步骤及哈希记录在该目录的 `sources.json`，介绍见其 `README.md`。资料著作权与适用许可仍归原权利人；应用代码的 MIT 许可不自动覆盖这些第三方资料。快照有去除网页导航、Markdown front matter 或添加来源标题等处理。

所有公开资料只用于解析与检索评测，不代表任一使用单位当前生效的制度，也不暗示资料发布方认可或支持本项目。下载的模型与 Python 依赖不随发布包分发，其许可由各自项目规定。
