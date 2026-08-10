// Cloudflare Worker：GitHub Actions 触发器（无服务器，免费）
// 作用：前端“刷新”按钮调用本 Worker，Worker 用持有的 GitHub Token 触发仓库的
//       refresh.yml（workflow_dispatch），实现“点按钮即命令云端立即重算基金数据”。
// 为什么需要它：GitHub API 触发 workflow 必须带鉴权 Token，不能把 Token 放在公开的前端页面里；
//               本 Worker 把 Token 存在服务端环境变量，前端只调用 Worker 地址，Token 不暴露。
//
// 部署步骤见 REFRESH_HOOK.md。

const OWNER = 'sgxxh';
const REPO = 'news-fund-dashboard';
const WORKFLOW = 'refresh.yml'; // 对应 .github/workflows/refresh.yml

export default {
  async fetch(request, env) {
    const cors = {
      'Access-Control-Allow-Origin': '*',
      'Content-Type': 'application/json',
    };
    // 处理浏览器预检请求
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: { ...cors, 'Access-Control-Allow-Methods': 'POST, OPTIONS' } });
    }
    if (request.method !== 'POST') {
      return new Response(JSON.stringify({ ok: false, msg: 'Method not allowed' }), { status: 405, headers: cors });
    }

    const token = env.GH_TOKEN;
    if (!token) {
      return new Response(JSON.stringify({ ok: false, msg: 'GH_TOKEN 未配置' }), { status: 500, headers: cors });
    }

    const url = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`;
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Accept': 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ ref: 'main' }),
      });
      if (!resp.ok) {
        const txt = await resp.text();
        return new Response(JSON.stringify({ ok: false, status: resp.status, msg: txt.slice(0, 200) }),
          { status: 502, headers: cors });
      }
      return new Response(JSON.stringify({ ok: true }), { headers: cors });
    } catch (e) {
      return new Response(JSON.stringify({ ok: false, msg: String(e) }), { status: 502, headers: cors });
    }
  }
};
