# 上传 GitHub

## 应该上传哪个目录

整理后的独立发布目录是 `github-release/zhixu-rag-agent/`。进入该目录后，应直接看到 `README.md`、`run.py`、`rag_agent/`、`web/`、`tests/`、`docs/`、`.github/` 和 `.env.example`，不应有正式 `.env`、`data/`、`.venv/`、个人文档或研究网页缓存。

也可以解压旁边的 `zhixu-rag-agent.zip`，进入解压得到的同名目录。**不要把 ZIP 当成仓库里唯一的文件**；应提交其中的完整目录内容，特别是 `.github/`、`.gitignore` 等隐藏文件。建议使用 Git 或 GitHub Desktop，避免漏传隐藏文件。

## 首次上传

当前项目仓库为 `wswwhcs9421/zhixu-rag-agent`，已经在 GitHub 初始化 README 与 MIT 许可证。此时应先克隆仓库，保留远端历史，再将发布目录里的文件（包括隐藏文件）复制到克隆目录。保留已有 `.git/`，不要复制 `.env` 或 `data/`。

已完成 SSH 认证时，可以使用：

```powershell
git clone git@github.com:wswwhcs9421/zhixu-rag-agent.git
cd zhixu-rag-agent
# 将准备好的发布目录内容复制到这里，再检查和提交
git add .
git status
git diff --cached --stat
git commit -m "Add Zhixu RAG Agent application and documentation"
git push -u origin main
```

克隆其他仓库时替换对应的实际地址。若 Git 提示未设置身份，在当前仓库执行 `git config user.name "你的名字"` 和 `git config user.email "你的邮箱"`，再提交。SSH 提示输入 passphrase 时，在自己的终端输入生成密钥时设置的保护密码。

如果使用全新且没有任何提交的空仓库，也可在发布目录 `git init`，然后关联远端。对于已经初始化的仓库，不需要使用强制推送，也不需要删除远端许可证。

第一次推送后，在 Actions 页面检查 Tests 工作流。工作流不需要配置 DeepSeek 密钥，不下载本地大模型；测试使用独立数据与模型替身。

## 发布目录如何生成

在源项目根目录执行：

```powershell
python scripts/build_github_release.py
```

脚本只按允许清单复制源码、文档、工作流、测试和必要的公开测试资料，不复制运行数据与网页研究缓存。生成目录、ZIP 和旁边的 `zhixu-rag-agent.manifest.json`，记录相对路径、大小、SHA256 和 ZIP 校验值。为了保留已生成版本，目标已存在时会拒绝覆盖；以后生成新目录可使用 `--output github-release/zhixu-rag-agent-v2`。

**直接提交原始工作目录不等于使用发布目录**。原目录中可保留自己的其他工作文件，发布脚本不会删除它们，也不会上传 GitHub。

## 后续维护

修改功能时同步更新测试、配置示例和文档，再重新构建并验证新发布目录。不要将正在运行的 `.env`、本地账号、向量数据库、上传文件或模型权重复制进仓库。

原创代码采用仓库已有的 MIT 许可证，发布包包含 `LICENSE`。第三方测试资料按其原有权利单独处理，见项目根目录的 `NOTICE.md`。
