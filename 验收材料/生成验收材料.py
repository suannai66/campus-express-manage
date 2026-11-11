"""从当前工作区生成 C 的完整源码快照、清单和可离线阅读的网页。"""
from pathlib import Path
from hashlib import sha256
from html import escape
from datetime import datetime
import ast
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
GUIDE = OUT / "C部分代码与验收讲解.md"
BASE_REF = "506db07"  # 首次 C 实现之前的团队基线；差异包含未提交的本次修订。
GROUPS = [
    ("12. C 部分完整业务源码", [
        ("backend/app/modules/fulfillment/__init__.py", "Python 包入口与模块说明"),
        ("backend/app/modules/fulfillment/contract.py", "请求字段、类型和条件校验"),
        ("backend/app/modules/fulfillment/models.py", "C 的五张业务表与唯一约束"),
        ("backend/app/modules/fulfillment/api.py", "HTTP 路由、查询权限、分页和评价提交"),
        ("backend/app/modules/fulfillment/service.py", "接单、履约、取消及同事务日志事件"),
        ("backend/app/modules/fulfillment/handlers.py", "完结事件校验、去重和评价开放"),
        ("backend/app/modules/fulfillment/credit.py", "最近 30 条取件评价均分"),
        ("backend/app/modules/fulfillment/migrate_receipt.py", "保留历史完结事实的确认收货流程迁移"),
        ("frontend/src/features/fulfillment/api.js", "C 前端请求封装和显示映射"),
        ("frontend/src/features/fulfillment/OrdersView.vue", "订单页面入口"),
        ("frontend/src/features/fulfillment/OrderWorkspace.vue", "订单工作台、履约交互和轮询"),
        ("frontend/src/features/fulfillment/OrderReviews.vue", "单个订单的双向评价"),
        ("frontend/src/features/fulfillment/ReviewsView.vue", "本人信用与评价页面"),
    ]),
    ("13. 修改过的公共接入与需求文档", [
        ("backend/app/main.py", "公共应用入口：接入 C 的表和路由"),
        ("backend/app/events/wiring.py", "公共事件订阅：接入 C 开放评价消费者"),
        ("backend/app/events/schema.py", "公共状态事件枚举：增加 completed"),
        ("backend/app/modules/orders/gateway.py", "B 受控写入口：发布者收货与配送动作分离"),
        ("backend/app/modules/orders/api.py", "B 查询：completed 状态过滤"),
        ("backend/app/modules/orders/projections.py", "B 既有大厅投影：兼容历史完结状态重命名"),
        ("backend/app/modules/finance/services/settlement.py", "D 结算消费者：仅 completed 可结算"),
        ("backend/app/modules/finance/README.md", "D 说明：收货后结算的集成边界"),
        ("backend/scripts/init_db.py", "初始化入口：注册 C 模型"),
        ("frontend/src/App.vue", "公共导航：更新订单和评价页的服务标签"),
        ("frontend/src/features/orders/PublishView.vue", "B 既有发布页：收货状态与详细地址提示文案"),
        ("frontend/src/features/orders/HallTaskDialog.vue", "B 既有大厅弹窗：仅提示接单后提供详细地址"),
        ("frontend/package.json", "前端命令：加入 C 浏览器测试"),
        ("backend/tests/test_events_integration.py", "公共事件集成测试：同时结算并开放评价"),
        ("README.md", "团队说明中的 C 启动、测试及演示说明"),
        ("docs/团队接口约定.md", "个人功能、质量、约束和交付契约"),
    ]),
    ("14. C 部分完整测试和测试配置", [
        ("backend/tests/test_fulfillment.py", "C 后端功能、并发、权限与收货边界测试"),
        ("backend/tests/test_receipt_migration.py", "旧流程无损迁移和冲突回滚测试"),
        ("backend/tests/test_finance_settlement.py", "D 结算边界与幂等回归测试"),
        ("backend/tests/test_finance_trade_audit.py", "跨订单资金守恒、退款结算竞争回归测试"),
        ("frontend/tests/fulfillment.spec.js", "浏览器验收场景"),
        ("frontend/playwright.fulfillment.config.js", "临时测试服务、端口和运行配置"),
    ]),
]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8").strip()


def language(path):
    return {".py": "python", ".vue": "vue", ".js": "javascript",
            ".json": "json", ".md": "markdown"}.get(Path(path).suffix, "text")


def main():
    commit = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    base_commit = git("rev-parse", BASE_REF)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    records = []
    for group, files in GROUPS:
        for path, role in files:
            raw = (ROOT / path).read_bytes()
            code = raw.decode("utf-8").replace("\r\n", "\n")
            records.append({"id": f"source-{len(records) + 1}", "path": path, "role": role,
                            "group": group, "lines": len(code.splitlines()),
                            "sha256": sha256(raw).hexdigest(), "code": code})
    changes = {r["path"]: re.sub(r"(?m)^(@@[^\n]*?)[ \t]+$", r"\1",
                              git("diff", "--unified=0", BASE_REF, "--", r["path"]))
               for r in records if r["group"].startswith("13.")}
    guide = GUIDE.read_text(encoding="utf-8").split("\n## 12.")[0].rstrip() + "\n"
    chunks = [guide]
    for group, files in GROUPS:
        chunks += [f"\n## {group}\n", "以下为当前文件完整内容；公共文件包含既有团队代码，其个人修改另见第 15 节。\n"]
        for rec in [r for r in records if r["group"] == group]:
            chunks += [f"\n### {rec['path']}\n\n{rec['role']}；{rec['lines']} 行。\n\n",
                       f"SHA-256（原始文件字节）：`{rec['sha256']}`\n\n",
                       f"~~~~{language(rec['path'])}\n", rec["code"],
                       "" if not rec["code"] or rec["code"].endswith("\n") else "\n", "~~~~\n"]
            if not rec["code"]:
                chunks.append("\n这是包标记文件，当前内容为空。\n")
    chunks.append(f"\n## 15. 公共文件中与 C 交付相关的修改\n\n以下逐文件展示团队基线 {BASE_REF} 到当前工作区的真实差异，涵盖首次 C 实现和本次确认收货修订，包含未提交修改；第 13 节展示当前完整文件。B/D 原文件的既有部分仍属于团队贡献，公共鉴权和投递器也不计为 C 原创。\n")
    for path, diff in changes.items():
        chunks += [f"\n### {path}\n\n~~~~diff\n{diff}\n~~~~\n"]
    GUIDE.write_text("".join(chunks), encoding="utf-8", newline="\n")
    method_counts = {}
    for rec in records:
        if rec["path"].startswith("backend/tests/"):
            tree = ast.parse(rec["code"])
            method_counts[rec["path"]] = sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                                                    and node.name.startswith("test_") for node in ast.walk(tree))
    manifest = {"headCommit": commit, "branch": branch, "snapshotKind": "working-tree",
                "generatedAt": generated_at, "diffBaseCommit": base_commit,
                "sourceFileCount": len(records), "testMethodDefinitions": method_counts,
                "note": "源码从当前工作区读取，包含未提交修订，不是 HEAD 提交快照；SHA-256 对应文件原始字节。完整公共代码不全属于 C 新增。生成材料不执行测试。",
                "files": [{k: v for k, v in r.items() if k != "code"} for r in records]}
    (OUT / "源码文件清单.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    render_html(guide, records, changes, commit, branch, generated_at)
    print(json.dumps({"files": len(records), "lines": sum(r["lines"] for r in records),
                      "commit": commit[:7], "outputs": [GUIDE.name, "C部分验收阅读版.html", "源码文件清单.json"]}, ensure_ascii=False))


def render_html(guide, records, changes, commit, branch, generated_at):
    paths = {r["path"]: r["id"] for r in records}
    headings = []
    heading_counter = 0

    def inline(text):
        text = escape(text)

        def link(m):
            label, href = m.groups()
            key = href.replace("D:/campusexpressmanage/", "")
            href = "#" + paths[key] if key in paths else href
            return f'<a href="{escape(href, quote=True)}">{label}</a>'

        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, text)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)

    def markdown(text):
        nonlocal heading_counter
        lines = text.splitlines()
        output, i = [], 0
        while i < len(lines):
            s = lines[i]
            if not s.strip():
                i += 1
                continue
            if s.startswith(("~~~", "```")):
                fence = s[:3]
                lang = s[3:]
                block = []
                i += 1
                while i < len(lines) and not lines[i].startswith(fence):
                    block.append(lines[i])
                    i += 1
                if lang == "mermaid":
                    output.append('<div class="flow" aria-label="主要状态流转"><span>待接单</span><b>→</b><span>已接单</span><b>→</b><span>取件中</span><b>→</b><span>配送中</span><b>→</b><span>已送达待收货</span><b>→</b><span>发布者确认收货</span><b>→</b><span>已完成：结算与互评</span></div>')
                    output.append('<details><summary>查看完整业务图的 Mermaid 源码</summary>')
                output.append(f'<pre class="example"><code>{escape(chr(10).join(block))}</code></pre>')
                if lang == "mermaid":
                    output.append('</details>')
                i += 1
                continue
            match = re.match(r"^(#{1,6}) (.+)$", s)
            if match:
                level, title = len(match[1]), match[2]
                heading_counter += 1
                anchor = f"explain-{heading_counter}"
                if level <= 2:
                    headings.append((anchor, title))
                output.append(f'<h{level} id="{anchor}">{inline(title)}</h{level}>')
                i += 1
                continue
            if s.startswith("|"):
                rows = []
                while i < len(lines) and lines[i].startswith("|"):
                    cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                    if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                        rows.append(cells)
                    i += 1
                output.append('<div class="table-scroll"><table>')
                for j, row in enumerate(rows):
                    tag = "th" if j == 0 else "td"
                    output.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in row) + "</tr>")
                output.append('</table></div>')
                continue
            if s.startswith("> "):
                output.append(f'<blockquote>{inline(s[2:])}</blockquote>')
                i += 1
                continue
            if re.match(r"^\d+\. ", s):
                output.append('<ol>')
                while i < len(lines) and re.match(r"^\d+\. ", lines[i]):
                    item_text = lines[i].split(". ", 1)[1]
                    output.append(f'<li>{inline(item_text)}</li>')
                    i += 1
                output.append('</ol>')
                continue
            para = [s]
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||>|~~~|```|\d+\. )", lines[i]):
                para.append(lines[i])
                i += 1
            output.append(f'<p>{inline(" ".join(para))}</p>')
        return "\n".join(output)

    explanation = markdown(guide)
    nav = ['<a class="brand" href="#top">C / 验收准备</a>', '<small>先讲业务，再对照源码</small>']
    nav += [f'<a href="#{anchor}">{escape(title)}</a>' for anchor, title in headings if not title.startswith("C 部分")]
    nav += [f'<a href="#source-library">完整源码 · {len(records)} 文件</a>']
    for group, _ in GROUPS:
        nav.append(f'<p class="nav-group">{escape(group)}</p>')
        nav += [f'<a class="source-link" href="#{r["id"]}">{escape(r["path"].split("/")[-1])}</a>' for r in records if r["group"] == group]
    cards = []
    for group, _ in GROUPS:
        cards.append(f'<h2>{escape(group)}</h2>')
        for rec in [r for r in records if r["group"] == group]:
            source = "".join(f'<span class="code-line" data-n="{n}">{escape(line) or " "}</span>' for n, line in enumerate(rec["code"].splitlines(), 1))
            code = f'<pre class="source-code"><code>{source}</code></pre>' if source else '<p class="empty">空文件，作为 Python 包标记。</p>'
            diff = changes.get(rec["path"], "")
            diff_html = f'<details class="diff"><summary>查看基线 {BASE_REF} 到当前工作区的公共文件修改</summary><pre class="example"><code>{escape(diff)}</code></pre></details>' if diff else ""
            cards.append(f'''<details class="source" id="{rec['id']}">
<summary><span>{escape(rec['path'])}</span><small>{rec['lines']} 行 · {escape(rec['role'])}</small></summary>
<div class="code-toolbar"><button type="button" data-copy="{rec['id']}">复制完整文件</button><span>SHA-256：{rec['sha256']}</span></div>
{code}{diff_html}</details>''')
    css = '''
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}body{margin:0;background:#f4f6f7;color:#24343c;font:16px/1.8 "Microsoft YaHei",system-ui,sans-serif}a{color:#1a6454;text-decoration:none}a:hover{text-decoration:underline}nav{position:fixed;inset:0 auto 0 0;width:272px;padding:28px 22px;background:#fff;border-right:1px solid #dde5e6;overflow:auto}nav a{display:block;font-size:14px;padding:5px 4px}nav .brand{font-size:21px;font-weight:800;color:#163e39}nav small{color:#647773;display:block;margin-bottom:24px}.nav-group{font-size:12px;color:#718381;margin:20px 0 4px}.source-link{font-family:Consolas,monospace}main{margin-left:272px;padding:40px clamp(24px,4vw,68px) 90px;max-width:1570px}.hero{padding:24px 28px;background:#173e3b;color:#eef9f6;border-radius:16px;margin-bottom:34px}.hero strong{font-size:26px}.hero p{margin:8px 0;color:#cee0da}.meta{font-size:13px}.hero a{color:#d1f3d8}h1{font-size:31px;line-height:1.4}h2{font-size:24px;border-bottom:2px solid #dce7e3;padding:22px 0 10px;margin-top:36px}h3{font-size:20px;margin-top:30px}h4{font-size:17px;color:#1a6254;margin-top:26px}p{margin:12px 0}blockquote{margin:20px 0;padding:18px 24px;border-left:4px solid #417c68;background:#e8f0eb;border-radius:0 10px 10px 0}.table-scroll{overflow-x:auto;margin:20px 0;border:1px solid #dce4e3;border-radius:10px}table{border-collapse:collapse;width:100%;font-size:14px;background:#fff}th,td{text-align:left;vertical-align:top;padding:12px 14px;border-bottom:1px solid #e4e9e9}th{background:#e6eeeb;color:#1d4b40}tr:last-child td{border-bottom:0}code{font-family:Consolas,"Microsoft YaHei",monospace;font-size:.91em;background:#e5ece8;padding:2px 5px;border-radius:4px}.example{background:#182b32;color:#e3eeec;padding:20px 24px;border-radius:10px;overflow:auto;font-size:14px;line-height:1.6}.example code,.source-code code{background:none;padding:0;border-radius:0;color:inherit;font-size:inherit}.flow{display:flex;gap:9px;align-items:center;flex-wrap:wrap;padding:22px;background:#fff;border-radius:12px;border:1px solid #dce5e1}.flow span{background:#e6f1e9;padding:7px 13px;border-radius:8px;color:#235845}.controls{position:sticky;top:0;z-index:2;background:#f4f6f7f5;backdrop-filter:blur(8px);padding:16px 0;display:flex;gap:10px;flex-wrap:wrap}.controls input{flex:1;min-width:180px;padding:12px 15px;border:1px solid #b7c7c1;border-radius:9px;font:inherit}button{border:1px solid #b7c7c1;border-radius:8px;background:#fff;color:#285a4d;padding:9px 14px;font:inherit;cursor:pointer}button:hover{background:#e6efea}details{margin:14px 0}summary{cursor:pointer;color:#2c5c4f}.source{border:1px solid #ccdcd7;border-radius:12px;overflow:hidden;background:#fff;scroll-margin-top:95px}.source>summary{padding:17px 20px;font-family:Consolas,"Microsoft YaHei",monospace;overflow-wrap:anywhere}.source>summary small{display:block;margin-left:18px;font-family:"Microsoft YaHei",system-ui,sans-serif;color:#6c7e77;font-size:13px}.source[open]>summary{background:#e7efe9}.code-toolbar{padding:10px 16px;border-top:1px solid #dce6df;display:flex;align-items:center;gap:16px;flex-wrap:wrap}.code-toolbar span{font:11px/1.6 Consolas,monospace;color:#758980;overflow-wrap:anywhere}.source-code{margin:0;background:#17272f;color:#e4eeec;overflow:auto;max-height:74vh;padding:17px 20px 17px 0;font:13px/1.65 Consolas,"Microsoft YaHei",monospace;tab-size:4}.code-line{display:block;min-height:1.65em;white-space:pre}.code-line:before{content:attr(data-n);display:inline-block;position:sticky;left:0;width:55px;padding-right:16px;margin-right:18px;text-align:right;color:#839590;background:#17272f;user-select:none;border-right:1px solid #33464c}.diff{padding:12px 20px}.empty{padding:10px 22px;color:#657d71}#match-count{font-size:13px;align-self:center;color:#667d71}#toast{position:fixed;bottom:24px;right:26px;background:#173e3b;color:white;padding:12px 20px;border-radius:9px;z-index:5;max-width:85vw}.footer{margin-top:40px;padding-top:20px;border-top:1px solid #cddbd5;color:#708377;font-size:13px}[hidden]{display:none!important}@media(max-width:960px){nav{position:static;width:auto;max-height:220px;border-right:0;border-bottom:1px solid #dce5e1;padding:18px 24px}nav a{display:inline-block;margin-right:13px}nav .brand,nav small{display:block}nav .nav-group,nav .source-link{display:none}main{margin:0;padding:24px 16px 60px}h1{font-size:26px}.hero{padding:20px}.hero strong{font-size:22px}.code-line:before{width:42px;margin-right:12px}.source-code{font-size:12px}.controls{padding:10px 0}}@media print{nav,.controls,button,#toast{display:none!important}main{margin:0;padding:0;max-width:none}.hero{color:#123;background:none;border:1px solid #bbb}.hero p{color:#123}.source-code{max-height:none;background:white;color:black;font-size:9px}.code-line:before{background:white;color:#888}body{background:white;font-size:11px}.source{break-inside:auto}.table-scroll{overflow:visible}}
'''
    source_data = json.dumps({r['id']: r['code'] for r in records}, ensure_ascii=False).replace('<', '\\u003c')
    script = '''
const sourceData=JSON.parse(document.getElementById('source-data').textContent);
const files=[...document.querySelectorAll('details.source')];
function followHash(){const el=document.getElementById(location.hash.slice(1));if(el&&el.matches('details.source')){el.hidden=false;el.open=true;requestAnimationFrame(()=>el.scrollIntoView({block:'start'}));}}
addEventListener('hashchange',followHash);followHash();
document.getElementById('file-search').addEventListener('input',e=>{const term=e.target.value.trim().toLowerCase();let n=0;files.forEach(el=>{el.hidden=!!term&&!el.textContent.toLowerCase().includes(term);if(!el.hidden)n++;});document.getElementById('match-count').textContent=n+' / '+files.length+' 个文件';});
document.getElementById('expand').onclick=()=>files.filter(el=>!el.hidden).forEach(el=>el.open=true);
document.getElementById('collapse').onclick=()=>files.forEach(el=>el.open=false);
let toastTimer;function toast(message){const el=document.getElementById('toast');el.textContent=message;el.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.hidden=true,3000);}
document.querySelectorAll('[data-copy]').forEach(button=>button.onclick=async e=>{e.stopPropagation();try{await navigator.clipboard.writeText(sourceData[button.dataset.copy]);toast('已复制完整文件');}catch{toast('当前浏览器不支持直接复制，请选中源码后复制。');}});
'''
    page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>C 部分完整代码与验收讲解</title><style>{css}</style></head><body id="top"><nav aria-label="阅读目录">{''.join(nav)}</nav><main><div class="hero"><strong>接单履约 · 发布者收货 · 评价信用</strong><p>完整代码与逐模块讲解 / 个人验收准备</p><p class="meta">当前工作区快照 · HEAD {commit[:7]} · {escape(branch)} · {len(records)} 个源文件</p><p class="meta">生成于 {escape(generated_at)} · 公共差异基线 {BASE_REF}；含未提交修订</p><p class="meta">测试结果见第 9.3 节；生成源码快照不会执行测试。</p></div>{explanation}<section id="source-library"><h1>完整源码阅读区</h1><p>文件默认折叠，点击文件名显示全部代码。可搜索路径或源码内容；公共接入文件另附基线到工作区的修改差异。</p><div class="controls"><input id="file-search" type="search" placeholder="搜索文件或源码，例如 confirm_receipt" aria-label="搜索源码"><button id="expand" type="button">展开全部</button><button id="collapse" type="button">收起全部</button><span id="match-count">{len(records)} / {len(records)} 个文件</span></div>{''.join(cards)}</section><p class="footer">源码与 SHA-256 从当前工作区读取，包含未提交修改，并非 HEAD 提交快照。公共代码包含团队既有实现，请结合实际差异说明个人贡献。数据库及个人账号数据未收录。</p></main><div id="toast" role="status" hidden></div><script>{script}</script></body></html>'''
    page = page.replace('<script>', f'<script id="source-data" type="application/json">{source_data}</script><script>', 1)
    (OUT / "C部分验收阅读版.html").write_text(page, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
