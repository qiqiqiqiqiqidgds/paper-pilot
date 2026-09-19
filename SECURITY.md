# 安全策略

## 报告漏洞

如果你发现了安全漏洞，请**不要开公开 Issue**，而是通过 GitHub 的
[私有漏洞报告（Report a vulnerability）](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-reviewing-vulnerabilities) 提交，
我们会尽快回应。

报告时请尽量包含：复现步骤、影响范围、可能的修复思路。

## 安全设计说明

- **论文数据本地化**：上传的论文、解析结果、生成的 PPT 全部保存在本地 `backend/data/`，不会上传到第三方（除你主动配置的 LLM / 搜索 API）。
- **API Key 存放**：LLM / 搜索 API Key 只保存在本地（`backend/.env` 或网页设置界面写入的 `backend/data/settings.json`），两者均被 `.gitignore` 排除，不会进入 git 仓库。请**永远不要**把真实 Key 提交到仓库或贴到 Issue 里。
- **服务端代理**：前端所有请求经 Next.js 服务端代理转发，浏览器端不持有后端地址与密钥。
- **鉴权与限流**：后端支持 `X-API-Key` 鉴权与按 IP 限流；公网部署时请配置 `APP_API_KEY` 与 `CORS_ORIGINS`。

## 已知注意事项

- 开发模式下 `start_dev` 脚本会把后端绑定到 `0.0.0.0`（局域网可达），仅供本机调试使用，请勿在不可信网络环境运行。
- 若你曾意外泄露过 API Key，请立即到对应平台吊销并重新签发。
