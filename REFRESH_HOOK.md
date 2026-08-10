# 点即刷：让网页“刷新”按钮命令云端立即重算

默认情况下，网页的“刷新”只是重新拉取 GitHub Pages 上**已有的**静态数据；云端数据靠 GitHub Actions 每 15 分钟自动重算。

如果你希望**在网页上点一下“刷新”，就命令云端立刻重新抓取养基宝 + 行情并刷新页面**，需要一个小的中间层来触发 GitHub Actions（因为触发接口必须带鉴权 Token，不能把 Token 放在公开的前端页面里）。

本方案用一个**免费的 Cloudflare Worker** 持有 Token，前端只调用 Worker 地址，Token 不暴露。

## 原理
```
网页“刷新”按钮
   └─> POST https://你的.workers.dev   （前端只知这个地址）
         └─> Worker 用 GH_TOKEN 调 GitHub API
               └─> 触发 refresh.yml (workflow_dispatch)
                     └─> GitHub Actions 重算基金 → 发布 gh-pages（约1分钟）
                           └─> 前端轮询检测到数据更新 → 自动重载
```

## 步骤（约 5 分钟，零费用）

### 1. 生成一个“仅能触发 Actions”的受限 Token
GitHub → 右上角头像 → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
- Token name：随意，如 `refresh-hook`
- Resource owner：选你自己
- Repository access：**Only select repositories** → 选 `news-fund-dashboard`
- Repository permissions → **Actions** → 设为 **Read and Write**（其余保持 No access）
- 拉到底点 **Generate token**，复制那一串 `github_pat_...`（只显示一次）

> 这个 Token 权限极小：只能触发/查看该仓库的 Actions，**不能读代码内容、不能改设置**，即使泄露风险也控制在“能被人触发布你的 workflow”范围内。

### 2. 部署 Cloudflare Worker（免费）
1. 打开 https://workers.cloudflare.com/ ，用邮箱注册（免费套餐足够）
2. **Workers & Pages → Create Worker**（或 Workers → 创建）
3. 把 `cloudflare-worker.js` 的**全部内容**粘贴进编辑器，覆盖默认代码
4. 点 **Deploy**，记下分配的地址（形如 `https://news-fund-dashboard-refresh.<你的子域>.workers.dev`）
5. 进入该 Worker → **Settings → Variables** → 添加环境变量：
   - 变量名 `GH_TOKEN`，值 = 第 1 步复制的 `github_pat_...`
   - 保存
6. 再点一次 **Deploy / 重试部署** 让变量生效（或编辑后 Save 会自动 redeploy）

### 3. 把 Worker 地址填进看板配置
编辑 `dist/data/backend.json`：
```json
{
  "mode": "github-pages",
  "refreshHook": "https://news-fund-dashboard-refresh.<你的子域>.workers.dev"
}
```
> 留空 `""` 时，刷新按钮退化为“仅重载当前静态数据”，行为与之前一致。

### 4. 推送并验证
```bash
# 在本机项目目录
git add -A
git commit -m "feat: 支持点即刷云端（refreshHook）"
git push origin main
```
推送后 GitHub Actions 会自动重建 `gh-pages`。等它跑完变绿，回到页面**硬刷新**（Ctrl/Cmd+Shift+R），点右上角“刷新”：
- 状态灯应显示「● 云端自动刷新（可点刷新立即重算）」
- 点击后约 1 分钟，页面自动更新为云端刚算完的最新估值

## 不想折腾？
不配置 `refreshHook` 也完全可用：云端每 **15 分钟**自动刷新一次，网页刷新按钮随时拉取最新静态结果。只有想“即时重算”才需要上面这套。
