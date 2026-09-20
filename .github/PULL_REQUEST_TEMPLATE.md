# Pull Request

## 改动说明

<!-- 做了什么、为什么。关联 Issue 用 "Closes #N" -->

## 改动类型

- [ ] Bug 修复（不引入新行为）
- [ ] 新功能
- [ ] 重构 / 文档
- [ ] 其他

## 自测清单

- [ ] 后端：`cd backend && python -m pytest tests/ -q` 全过（新增逻辑已补测试）
- [ ] 后端：`ruff check app/ tests/` 零告警
- [ ] 前端：`cd frontend && npm test && npx tsc --noEmit -p tsconfig.json` 全过
- [ ] 前端：`npm run lint` 零错误
- [ ] 涉及 UI 的改动已做浏览器实测（含暗色模式 / 375px 移动端）
- [ ] 涉及桌面版打包链的改动已跑 `desktop/npm run smoke`

## 截图 / 录屏（UI 改动必填）
