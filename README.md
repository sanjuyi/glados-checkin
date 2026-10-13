# GLaDOS 自动签到（GitHub Actions）

用 GitHub Actions 每天自动给 [GLaDOS](https://glados.rocks) 签到，电脑不用开机，不用装 Python。
参考项目：[kingkare/GLaDOS](https://github.com/kingkare/GLaDOS)（本仓库在其逻辑上修掉了几个会误判的问题，见文末「和原项目有什么区别」）。

签到时间：**每天 UTC 01:00 = 北京时间 09:00**。结果会写在 Actions 运行页面的 Summary 里（可选推 Telegram）。

---

## 一次性部署（约 5 分钟）

### 第 1 步：拿到 cookie

cookie 等于账号凭证，**只能放进 GitHub Secrets，不要提交到仓库、不要发到聊天里**。
先确保浏览器里**已经登录** glados.rocks（没登录取的 cookie 是无效的）。

**方法 A（推荐，最不容易出错）：整行复制 Cookie 请求头**

1. 在 glados.rocks 的**签到页面**（`/console/checkin`）按 `F12` 打开开发者工具。
2. 切到 **Network**（中文版「网络」）标签，按 `F5` 刷新一次页面。
3. 在请求列表里点任意一个 **`api/user/...`** 请求（例如 `status` 或 `checkin`）。
4. 右侧 **Headers → Request Headers**，找到 **`Cookie:`** 那一行，把**整行的值**复制下来：

   ```
   koa:sess=xxxxxxx...; koa:sess.sig=yyyyyyy...
   ```

   这样不会漏字段，也不用自己拼。脚本会自动去掉行首可能带上的 `Cookie:` 字样和多余空格。

**方法 B：从 Cookies 面板里逐条复制**

1. `F12` → **Application / 应用程序** → 左侧 **Storage → Cookies → https://glados.rocks**。
2. 在过滤框里输入 `koa`，会看到两条：
   - `koa:sess`
   - `koa:sess.sig`
3. 分别双击它们的 **Value** 列复制，然后按 `名字=值` 拼成一行，中间用 `; ` 分隔：

   ```
   koa:sess=<koa:sess 的 Value>; koa:sess.sig=<koa:sess.sig 的 Value>
   ```

   ⚠️ **两条都要**。只复制第一条（`koa:sess` 或 `gld:sess`）会一直签到失败——这是最常见的翻车原因（脚本会提示「cookie 只复制了一半」）。

> 名称说明：`glados.rocks` 用 `koa:sess` + `koa:sess.sig`；`glados.network` 等其它域名历史上出现过
> `gld:sess` + `gld:sess.sig`。方法 A 不管叫什么名字都能一次拿全，所以更推荐。

cookie 是有有效期的，失效后工作流会变红提醒你，到时重新复制一次、更新 Secret 即可。

### 第 2 步：建仓库并推上去

在 `glados-checkin` 文件夹里执行（PowerShell）：

```powershell
powershell -ExecutionPolicy Bypass -File .\push-to-github.ps1
```

脚本会：初始化 git → 提交文件 → 打开 GitHub「新建仓库」页面（**建一个空的**，不要勾 README）→ 你把仓库地址粘回去 → 它自动 push（第一次会弹出浏览器让你登录 GitHub）。

想建私有仓库（签到同样能用，免费额度 2000 分钟/月，本任务每天约 1 分钟）就加参数：

```powershell
powershell -ExecutionPolicy Bypass -File .\push-to-github.ps1 -Visibility private
```

装了 GitHub CLI 并 `gh auth login` 过的话，脚本会直接帮你建仓库+推送，连开网页都省了。

### 第 3 步：配置 Secrets 并跑一次

1. 仓库页面 → **Settings** → 左侧 **Secrets and variables** → **Actions** → **New repository secret**。

   | Secret 名称 | 是否必需 | 说明 |
   |---|---|---|
   | `GLADOS_COOKIE_1` | ✅ 必需 | 第 1 步复制的 cookie |
   | `GLADOS_COOKIE_2` / `_3` … | 可选 | 更多账号，**编号必须连续**，中间断了后面的就取不到 |
   | `GLADOS_COOKIE` | 可选 | 单账号写法（与 `GLADOS_COOKIE_1` 二选一即可） |
   | `TG_BOT_TOKEN` | 可选 | Telegram 机器人 Token，不填则不推送 |
   | `TG_CHAT_ID` | 可选 | Telegram 接收目标 |

   名称必须**一模一样**（区分大小写，别加空格）。

2. 仓库页面 → **Actions** 标签。如果提示 *Workflows aren't being run on this forked repository* 之类的字样，点一次 **"I understand my workflows, go ahead and enable them"**。

3. 左侧选 **GLaDOS 自动签到** → 右侧 **Run workflow** 手动跑一次验证。跑完点进去看：
   - 绿色 ✅ + Summary 里显示「签到成功，获得 N 积分」或「今日已签到」= 成功。
   - 红色 ❌ = 看日志里的中文说明（一般是 cookie 失效）。

之后不用再管，每天 09:00（北京时间）自动跑。

---

## 手动运行 / 换 cookie

- 想立刻补签：Actions → GLaDOS 自动签到 → Run workflow。
- cookie 失效：重新做第 1 步，然后 Settings → Secrets → 点 `GLADOS_COOKIE_1` → **Update** 覆盖值。

### 本机跑（可选，需要自己装 Python 3.8+）

```powershell
python -m pip install requests
$env:GLADOS_COOKIE_1 = "koa:sess=...; koa:sess.sig=..."
python .\checkin.py
```

---

## 和原项目有什么区别

原项目（`checkin.py` / `glados.py`）能跑，但有几处会**误报成功**或做无用功，本仓库做了修正：

| 问题 | 原项目 | 本仓库 |
|---|---|---|
| 判成败的方式 | `glados.py` 用 `raise_for_status()`：cookie 失效时服务端返回 HTTP 502，会被当成网络异常；`checkin.py` 只要响应体里有 `code` 就当成签到成功 | 只看响应体里的 `code` / `message`，明确区分「签到成功 / 今日已签 / cookie 失效 / 网络不通 / 非 JSON 响应」五类 |
| **误报成功** | `checkin.py` 里 `if "code" in data` 恒为真：cookie 失效时会推送「**✅ GLaDOS 签到通知**」，状态信息写「无返回信息」或「没有权限」，实际什么都没签到 | 非成功、非重复一律判失败，工作流标红，人一眼看得到 |
| 域名硬编码 | `glados.py` 只打 `glados.rocks`，这个域名抽风就没救 | 依次尝试 `glados.rocks` / `glados.cloud` / `glados.network` / `glados.one` |
| 不可达域名会拖时间 | 会一直卡在超时上 | 连接超时 8 秒、失败即跳过，不阻塞 |
| 60 天没活动定时任务被 GitHub 自动禁用 | 无对策 | 每月 1 号一个「保活」空提交 |
| 依赖 `python-dotenv` | `glados.py` 需要它读 `.env` | 只依赖 `requests`，`.env` 走 `.gitignore` 排除 |
| Telegram 通知静默失败 | 原项目推送失败（或没配）只打一行日志，不看运行页面根本发现不了 | 每次运行都把 Telegram 状态（已推送 / 未推送缺哪个变量 / 失败原因）写进日志和 Actions 摘要 |

> **实测依据**（本机真实请求，用的是脚本自己那套请求头）：
> - 会话无效（被踢下线、漏复制 `koa:sess.sig`、或值是伪造的）时，`POST /api/user/checkin` 与 `GET /api/user/status`
>   都返回 `HTTP 200` + `{"code":-2,"message":"没有权限"}`；
> - 同样是无效 cookie，若请求头极简（只有 `Cookie`）则返回 `HTTP 502` + `{"code":-1}`（无 `message`）。
>   同一个失败状态既能是 200 又能是 502，所以 **HTTP 状态码本身不能当判定依据** —— 这正是原脚本误报成功的根源。
> - `glados.network` 曾被解析到 `face:b00c`、`glados.one` 曾被解析到 `93.46.8.90`（DNS 污染）而完全连不上，
>   但也出现过能连通的时候，因此脚本对这四个域名做容错尝试，而不是硬编码单个域名。

---

## 排查表

| 现象 | 原因 / 处理 |
|---|---|
| 工作流红色，日志「Cookie 无效或已过期」 | cookie 过期，重新复制更新 Secret |
| 工作流红色，日志「未找到任何 cookie」 | Secret 名字拼错，或编号从 `_2` 开始导致读取中断；确认有 `GLADOS_COOKIE_1` |
| 日志里 `glados.network: 连接失败` | 该域名可能被 DNS 污染，脚本会自动换下一个域名；只要有一个域名成功就没问题 |
| 日志里「cookie 只复制了一半：缺少带签名的那条」 | 只复制了 `koa:sess` / `gld:sess`，漏了带签名的 `*.sig` 那条；两条的值都要，用 `; ` 连成一行 |
| 提示「今日已签到（重复签到，正常）」 | 正常，说明当天额度已经拿到 |
| Telegram 没收到消息 | **先看运行页面的 Summary**：现在每次运行都会写明「Telegram 通知：已推送（message_id=…）」/「未推送：Secret 里缺少 TG_BOT_TOKEN / TG_CHAT_ID」/ 具体失败原因。另外 Telegram 不允许 bot 主动开新会话，得先给 bot 发过一条消息（如 `/start`） |
| 定时任务某天没跑 | GitHub 的 cron 高峰期会延迟几分钟到几十分钟；另外仓库 60 天完全无活动会被自动停用（点邮件里的 Re-enable，或依赖每月保活提交） |
| 保活步骤报权限错误 | Settings → Actions → General → Workflow permissions 选 **Read and write permissions**；不影响签到本身 |

---

## 安全提示

- cookie 泄露 ≈ 账号被接管。只放在 GitHub Secrets（加密存储，日志中自动打码）。
- `.gitignore` 已排除 `.env`，本地调试别把 cookie 直接写进任何会提交的文件。
- 怀疑泄露：去 GLaDOS 官网退出登录使旧 session 失效，再重新取 cookie。
- 本仓库只做 `POST /api/user/checkin` 和 `GET /api/user/status` 两个请求，不碰其它任何数据。
