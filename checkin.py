# -*- coding: utf-8 -*-
"""GLaDOS 每日自动签到（GitHub Actions 与本机运行通用）。

配置（全部通过环境变量传入，绝不写进代码库）：
    GLADOS_COOKIE      单账号 cookie
    GLADOS_COOKIE_1    多账号：GLADOS_COOKIE_1 / _2 / _3 / ... 连续编号，遇到第一个空值就停止
    TG_BOT_TOKEN       可选，Telegram 机器人 Token，不填则跳过推送
    TG_CHAT_ID         可选，Telegram 接收目标（用户 id 或群组 id）

设计要点（都来自对真实接口的实测，不是猜的）：
    * HTTP 状态码本身不能当判定依据：同一个"未登录"状态，会话无效时服务端返回
      HTTP 200 + {"code": -2, "message": "没有权限"}，而请求头极简时返回 HTTP 502 + {"code": -1}；
      签到成功同样是 HTTP 200。所以必须解析响应体，绝不能用 raise_for_status()。
    * 状态接口 /api/user/status 在 cookie 失效时返回 HTTP 200 + {"code": -2, "message": "没有权限"}。
    * 依次尝试 glados.rocks / glados.cloud / glados.network / glados.one：
      实测国内直连时 glados.network / glados.one 曾被 DNS 污染（解析到 93.46.8.90 / face:b00c）
      而完全连不上，但也出现过能连通的时候，所以做成容错跳过而不是硬编码单个域名。
    * 只有当返回体里出现明确结论（code == 0 或带 message）才停止尝试，
      否则换下一个 token / 域名继续试。

退出码：
    0 = 所有账号都拿到了明确结果（签到成功或今日已签到）
    1 = 有任何账号失败（cookie 失效、网络不通、返回无法识别）——让工作流变红提醒你处理
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import requests

DOMAINS = ["glados.rocks", "glados.cloud", "glados.network", "glados.one"]
TOKENS = ["glados.one", "glados.network"]
TIMEOUT = (8, 15)  # (连接超时, 读取超时)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
BEIJING = timezone(timedelta(hours=8))

CODE_OK = 0
CODE_REPEAT = 1
CODE_NO_AUTH = -1
CODE_NO_PERM = -2


def normalize_cookie(raw: str) -> str:
    """把用户复制过来的 cookie 收拾干净：去掉 'Cookie:' 前缀、换行和多余空格。"""
    text = (raw or "").strip()
    if text.lower().startswith("cookie:"):
        text = text[len("cookie:"):]
    return " ".join(text.split())


def build_headers(cookie: str, domain: str) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Content-Type": "application/json;charset=UTF-8",
        "Cookie": cookie,
        "Origin": f"https://{domain}",
        "Referer": f"https://{domain}/console/checkin",
        "User-Agent": USER_AGENT,
    }


def classify(code, message: str) -> tuple[str, str]:
    """把服务端返回翻译成 (状态, 中文说明)。

    状态取值：ok / repeat / noauth / unknown
    """
    text = (message or "").strip()
    low = text.lower()

    if code == CODE_OK or "checkin! got" in low:
        points = ""
        if "got" in low and " points" in low:
            try:
                points = text.split("Got ", 1)[1].split(" Points", 1)[0].strip()
            except IndexError:
                points = ""
        detail = f"，获得 {points} 积分" if points else ""
        return "ok", f"签到成功{detail} 🎉"

    if (
        code == CODE_REPEAT
        or "repeat" in low
        or "already" in low
        or "try tomorrow" in low
    ):
        return "repeat", "今日已签到（重复签到，正常）🔁"

    if (
        code in (CODE_NO_AUTH, CODE_NO_PERM)
        or "not logged in" in low
        or "login" in low
        or "forbidden" in low
        or "没有权限" in text
    ):
        return "noauth", "Cookie 无效或已过期，请重新获取并更新 GitHub Secret ⚠️"

    if not text:
        return "unknown", f"服务端没有返回可识别的信息（code={code}）❓"

    return "unknown", f"未知结果：{text} ❓"


def do_checkin(cookie: str) -> dict:
    """按域名 × token 依次尝试签到，返回第一个明确结论。"""
    attempts = []
    got_response = False  # 收到过 HTTP 响应（哪怕是错误码）
    got_json = False      # 收到过可解析的 JSON

    for domain in DOMAINS:
        url = f"https://{domain}/api/user/checkin"
        headers = build_headers(cookie, domain)

        for token in TOKENS:
            try:
                resp = requests.post(
                    url, headers=headers, json={"token": token}, timeout=TIMEOUT
                )
            except requests.RequestException as exc:
                # 域名不通（被污染/被墙），不必再试这个域名的其它 token
                attempts.append(f"{domain}: 连接失败（{type(exc).__name__}）")
                break

            got_response = True
            try:
                data = resp.json()
            except ValueError:
                attempts.append(f"{domain}: 非 JSON 响应（HTTP {resp.status_code}）")
                break

            got_json = True
            code = data.get("code")
            message = str(data.get("message") or "")

            # 有明确结论就收工；只有 code=-1 且无 message 才是"没登录"，继续换下一个试
            if code == CODE_OK or message:
                state, text = classify(code, message)
                return {
                    "state": state,
                    "text": text,
                    "domain": domain,
                    "token": token,
                    "code": code,
                    "raw": message,
                    "attempts": attempts,
                }

            attempts.append(f"{domain}({token}): code={code} 且无 message")

    # 所有域名都试完了，按最可能的原因报错（三种情况都能真实发生，别合并）
    if not got_response:
        state, text = "fail", "所有域名都连不上（DNS 污染或网络不通）🌐"
    elif not got_json:
        state, text = "fail", "所有域名都返回了无法解析的响应，服务端可能临时故障 🌐"
    else:
        state, text = "noauth", classify(CODE_NO_AUTH, "")[1]

    return {
        "state": state,
        "text": text,
        "domain": None,
        "token": None,
        "code": CODE_NO_AUTH,
        "raw": "",
        "attempts": attempts,
    }


def fetch_status(cookie: str) -> dict:
    """查账号邮箱和剩余天数；失败时返回未知，不影响签到结果。"""
    for domain in DOMAINS:
        try:
            resp = requests.get(
                f"https://{domain}/api/user/status",
                headers=build_headers(cookie, domain),
                timeout=TIMEOUT,
            )
            data = resp.json()
        except (requests.RequestException, ValueError):
            continue

        code = data.get("code")
        if code == CODE_OK:
            info = data.get("data") or {}
            return {"email": info.get("email") or "未知", "left_days": info.get("leftDays")}
        if code in (CODE_NO_AUTH, CODE_NO_PERM):
            return {"email": "未知", "left_days": None}

    return {"email": "未知", "left_days": None}


def format_expire(left_days) -> str:
    if left_days is None:
        return "未知"
    try:
        days = float(left_days)
    except (TypeError, ValueError):
        return str(left_days)
    expire = datetime.now(BEIJING) + timedelta(days=days)
    return f"{expire.strftime('%Y-%m-%d')}（剩余 {days:.2f} 天）"


def collect_accounts() -> list:
    accounts = []

    single = normalize_cookie(os.environ.get("GLADOS_COOKIE", ""))
    if single:
        accounts.append({"label": "GLADOS_COOKIE", "cookie": single})

    index = 1
    while True:
        raw = normalize_cookie(os.environ.get(f"GLADOS_COOKIE_{index}", ""))
        if not raw:
            break
        accounts.append({"label": f"GLADOS_COOKIE_{index}", "cookie": raw})
        index += 1

    return accounts


def cookie_warning(cookie: str) -> str:
    """本地预检：cookie 抄漏了是最常见的失败原因，提前给人话提示。

    实测行为（本机真实请求，用的是脚本自己那套请求头）：
        * 只带 koa:sess、不带签名那条 -> HTTP 200 + {"code": -2, "message": "没有权限"}，签到必然失败
        * 两条都带但值是伪造的（等价于被踢下线） -> 完全相同的返回
    所以这条提示只是提前告诉你抄漏了哪一段，成败判定仍然以服务端返回为准。

    名字不写死：glados.rocks 用 koa:sess / koa:sess.sig，其它域名出现过 gld:sess / gld:sess.sig。
    """
    if "=" not in cookie:
        return (
            "这看起来不是 cookie（没有 name=value 形式）。请复制浏览器 Network 里的 Cookie 请求头整行，"
            "或在 Application → Cookies 里把名字和值按 name=value 拼好"
        )

    names = [
        part.split("=", 1)[0].strip().lower()
        for part in cookie.split(";")
        if "=" in part
    ]
    if names and not any(name.endswith(".sig") for name in names):
        return (
            "cookie 只复制了一半：缺少带签名的那条（glados.rocks 上是 koa:sess.sig，"
            "glados.network 上是 gld:sess.sig）。两条的值都要，用 '; ' 连成一行"
        )
    return ""


def send_telegram(token: str, chat_id: str, text: str) -> None:
    if not token or not chat_id:
        print("未配置 TG_BOT_TOKEN / TG_CHAT_ID，跳过 Telegram 推送。")
        return
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            print(f"Telegram 推送失败：HTTP {resp.status_code} {resp.text[:200]}")
    except requests.RequestException as exc:
        print(f"Telegram 推送失败：{exc}")


def write_step_summary(markdown: str) -> None:
    """在 GitHub Actions 运行页面上显示一张结果表。本地运行时会自动跳过。"""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    except OSError as exc:
        print(f"写入 Actions 摘要失败：{exc}")


def main() -> int:
    now = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M")
    accounts = collect_accounts()

    if not accounts:
        msg = (
            "❌ <b>GLaDOS 签到未执行</b>\n"
            "原因：没有读到 cookie。请在仓库 Settings → Secrets and variables → Actions "
            "里添加 <code>GLADOS_COOKIE_1</code>（或 <code>GLADOS_COOKIE</code>）。"
        )
        print(msg)
        write_step_summary(f"## ❌ GLaDOS 签到未执行\n\n{now}（北京时间）\n\n未读到 cookie。")
        send_telegram(
            os.environ.get("TG_BOT_TOKEN", ""), os.environ.get("TG_CHAT_ID", ""), msg
        )
        return 1

    rows = []
    tg_lines = []
    failed = 0

    for order, account in enumerate(accounts, 1):
        hint = cookie_warning(account["cookie"])
        result = do_checkin(account["cookie"])
        status = fetch_status(account["cookie"])
        expire = format_expire(status["left_days"])

        if result["state"] not in ("ok", "repeat"):
            failed += 1
            if hint:
                # 失败且 cookie 本身有问题时，把原因直接写进结果里，别让人去翻文档
                result["text"] = f"{result['text']}｜{hint}"

        head = f"#{order} {status['email']}"
        line = f"{head} | {result['text']} | 到期：{expire}"
        rows.append(line)
        tg_lines.append(f"<b>{head}</b>：{result['text']}\n到期时间：<code>{expire}</code>")

        print(f"[{now}] {line}")
        if hint and result["state"] in ("ok", "repeat"):
            print(f"        ⚠️ {account['label']}：{hint}")
        if result["attempts"]:
            print("        尝试记录：" + "；".join(result["attempts"]))

    summary_text = "\n".join(tg_lines)
    total = len(accounts)
    ok_count = total - failed
    icon = "✅" if failed == 0 else "⚠️"

    print("\n===== 结果汇总 =====")
    for line in rows:
        print(line)
    print(f"成功 {ok_count}/{total}")

    write_step_summary(
        f"## {icon} GLaDOS 签到结果（{now} 北京时间）\n\n"
        + "\n".join(f"- {line}" for line in rows)
        + f"\n\n成功 **{ok_count}/{total}**\n"
    )

    send_telegram(
        os.environ.get("TG_BOT_TOKEN", ""),
        os.environ.get("TG_CHAT_ID", ""),
        f"{icon} <b>GLaDOS 签到结果</b>（{now} 北京时间）\n\n{summary_text}\n\n成功 {ok_count}/{total}",
    )

    return 1 if failed else 0


if __name__ == "__main__":
    # 本机 Windows 控制台默认不是 UTF-8，这里兜一下，避免中文输出报错
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main())
