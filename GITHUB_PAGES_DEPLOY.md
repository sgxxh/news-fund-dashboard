# 部署到 GitHub Pages（纯云端 · 免费 · 关机也实时刷新）

把看板搬到 GitHub Pages：前端是静态页，后端逻辑由 **GitHub Actions** 定时跑。
不花一分钱、不依赖本机/路由器，电脑关机时 Actions 仍在云端按时刷新基金估值。

---

## 原理

- `dist/` 是纯静态前端（HTML/CSS/JS + 数据 JSON），由 GitHub Pages 托管。
- 两个 GitHub Actions 工作流（已放好 `.github/workflows/`）：
  - **基金定时刷新（云端）**：交易时段每 30 分钟跑一次 `refresh_now.py`，从养基宝拉最新持仓与估值，重新生成 `dist/data`，发布到 `gh-pages` 分支。
  - **每日全量构建（云端）**：每个交易日早 08:00（北京）跑一次完整管道，补当日新闻与市场情绪。
- 养基宝登录态通过仓库 **Secret `YJB_TOKEN`** 注入，不写进代码。

> 隐私提示：GitHub Pages 站点地址对任何人可见（即使仓库设为私有，页面本身仍公开）。
> 若不想暴露自己的基金持仓，**请改用轻量云 VPS 方案**（数据只在你自己的服务器上）。

---

## 一、在 GitHub 建空仓库

1. 登录 https://github.com → New repository。
2. 仓库名随意，例如 `news-fund-dashboard`。
3. **建议设为 Private**（代码/养基宝常量不外泄；页面仍公开）。
4. **不要**勾选 “Add a README”，保持空仓库。
5. 创建后，复制仓库的 HTTPS 地址，形如 `https://github.com/<你的用户名>/news-fund-dashboard.git`。

---

## 二、把本地项目推上去

在本项目目录（`news-fund-dashboard/`）打开终端，执行：

```bash
git init
git add -A
git commit -m "init: 新闻·基金工作台 静态前端 + 云端刷新工作流"
git branch -M main
git remote add origin https://github.com/<你的用户名>/news-fund-dashboard.git
git push -u origin main
```

推送时会要求 GitHub 账号密码：**密码处填 Personal Access Token（PAT）**，不是网页登录密码。
PAT 需勾选 `repo` 权限，在 https://github.com/settings/tokens 生成。

> 仓库里已包含 `data/daily/*.json`（历史新闻）与 `dist/`（前端+数据），所以首次推送即有内容。

---

## 三、放入养基宝 Token（关键）

1. 打开本机文件：`C:\Users\sgx\.yjb_token.json`（Git Bash 里是 `~/.yjb_token.json`）。
2. 里面形如 `{ "token": "长字符串" }`，复制 `token` 的值。
   （若文件不存在，先在电脑端跑一次采集触发养基宝扫码登录即可生成。）
3. 进入仓库 **Settings → Secrets and variables → Actions → New repository secret**。
4. Name 填 `YJB_TOKEN`，Secret 填刚才复制的 token 值，保存。

---

## 四、开启 GitHub Pages

1. 仓库 **Settings → Pages**。
2. Source 选 **Deploy from a branch**。
3. Branch 选 **gh-pages**，目录 **/(root)**，Save。
4. 稍等 1–2 分钟，顶部会出现站点地址，形如：
   `https://<你的用户名>.github.io/news-fund-dashboard/`

---

## 五、验证 & 日常使用

- 进入仓库 **Actions** 标签页，能看到 `基金定时刷新（云端）` 和 `每日全量构建（云端）` 两个工作流。
- 首次推送后，Actions 会在交易时段按调度自动跑；也可手动触发：
  Actions → 选工作流 → **Run workflow**。
- 打开站点地址，顶部状态灯应显示 **● 云端自动刷新（每交易日约30分钟）**。
- 点右上角“刷新”按钮 = 重新加载云端最新已发布数据（Actions 每 30 分钟自动刷新一次）。
- 点开某只基金 → “刷新估值” = 重载该基金最新详情文件。

---

## 六、维护

- **Token 过期**：养基宝重新登录后，更新仓库 Secret `YJB_TOKEN` 的值即可。
- **改了管道代码**：`git push` 新提交；Actions 下次调度或手动 Run 会重新构建。
- **想加新闻更及时**：手动在 Actions 跑一次“每日全量构建（云端）”。
- **彻底不想用 GitHub**：见 `server.py` / `Dockerfile` / `start.sh`（VPS 方案残留文件，可删）。

---

## 七、费用与限制

- GitHub Actions：私有仓库免费额度 2000 分钟/月，本方案每月约几百分钟，完全够用。
- 调度精度：GitHub 定时任务可能延迟几分钟，基金估值用于参考足够；介意可改 VPS。
- 站点公开：见上方隐私提示。
