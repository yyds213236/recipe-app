#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日一点 —— 小锅菜谱的本机每日小优化。

用法：
  python3 tools/daily_tune.py --dry-run      # 只看今天会改什么，一个字都不写
  python3 tools/daily_tune.py                # 改一个地方 → 跑校验 → 提交
  python3 tools/daily_tune.py --push         # 同上，提交后 git push
  python3 tools/daily_tune.py --retry-failed # 把失败的条目放回队列

机制：
  backlog.json 是一个有序数组，每天取第一个「还没做过」的条目，按 kind
  插入/替换/追加一小段代码，跑 node check.js 验证，通过才提交。
  进度记在 tools/applied.json 里，所以同一项永远不会做第二次。
  backlog 全部做完后自动进入「巡检模式」：只核对 README 里的统计数字。

设计取舍：
  * 一次只碰一个文件（new_file 也是只新增一个），提交历史干净、好 revert。
  * 校验失败立刻还原成原样（内存快照优先，文件本来是干净的跟踪文件时用
    git checkout --），再把这一项标成 failed 接着试下一项，绝不死循环。
  * 所有输出都走 stdout，launchd 直接重定向进日志文件。
  * 任何未预料的异常都会打印 traceback 并以非零退出，不会静默失败。
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKLOG_PATH = ROOT / "tools" / "backlog.json"
STATE_PATH = ROOT / "tools" / "applied.json"
README_PATH = ROOT / "README.md"

MAX_ATTEMPTS = 5          # 一次运行最多尝试几项（防止一晚上刷掉整个 backlog）
CHECK_TIMEOUT = 120       # node check.js 的超时秒数


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def log(msg=""):
    print(msg, flush=True)


def today():
    return datetime.date.today().isoformat()


def find_node():
    """找一个能用的 node；找不到返回 None（就跳过 JS 校验，不拦着干活）。"""
    candidates = [
        Path.home() / ".local" / "bin" / "node",
        Path("/opt/homebrew/bin/node"),
        Path("/usr/local/bin/node"),
    ]
    which = shutil.which("node")
    if which:
        candidates.append(Path(which))
    for path in candidates:
        try:
            if path.is_file() and os.access(str(path), os.X_OK):
                return str(path)
        except OSError:
            continue
    return None


def run(cmd, cwd=None, timeout=300):
    """跑命令，返回 (returncode, stdout+stderr)。"""
    proc = subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def git(*args, check=True):
    code, out = run(["git"] + list(args))
    if check and code != 0:
        raise RuntimeError("git %s 失败（%d）：%s" % (" ".join(args), code, out.strip()))
    return code, out


# --------------------------------------------------------------------------- #
# backlog / 状态
# --------------------------------------------------------------------------- #
def load_backlog():
    data = json.loads(BACKLOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError("tools/backlog.json 必须是数组")
    seen = set()
    for item in data:
        for key in ("id", "title", "kind", "file"):
            if not item.get(key):
                raise RuntimeError("backlog 条目缺少字段 %s：%r" % (key, item))
        if item["id"] in seen:
            raise RuntimeError("backlog 里 id 重复：%s" % item["id"])
        seen.add(item["id"])
        if item["kind"] not in ("insert", "replace", "append", "new_file"):
            raise RuntimeError("%s 的 kind 不认识：%s" % (item["id"], item["kind"]))
    return data


def load_state():
    if not STATE_PATH.exists():
        state = {"applied": [], "runs": [], "failed": {}}
        save_state(state)
        return state
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    state.setdefault("applied", [])
    state.setdefault("runs", [])
    state.setdefault("failed", {})
    return state


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def pick_next(backlog, state):
    """第一个既没做过、也没被标失败的条目。"""
    done = set(state["applied"])
    failed = set(state["failed"].keys())
    for item in backlog:
        if item["id"] not in done and item["id"] not in failed:
            return item
    return None


def backlog_progress(backlog, state):
    done = len([i for i in backlog if i["id"] in set(state["applied"])])
    return done, len(backlog)


# --------------------------------------------------------------------------- #
# 应用一个条目
# --------------------------------------------------------------------------- #
class ItemError(Exception):
    pass


def _read(path):
    return path.read_text(encoding="utf-8")


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _already_done(item):
    """幂等判断：文件里已经有 marker（或新文件已存在）就跳过。"""
    target = ROOT / item["file"]
    if item["kind"] == "new_file":
        return target.exists()
    marker = item.get("marker")
    if not marker or not target.exists():
        return False
    return marker in _read(target)


def _apply_insert(item, text):
    anchor = item["anchor"]
    content = item["content"]
    hits = text.count(anchor)
    if hits != 1:
        raise ItemError(
            "anchor 在 %s 里出现 %d 次（要求恰好 1 次）：%r"
            % (item["file"], hits, anchor[:80])
        )
    if item.get("before"):
        return text.replace(anchor, content + anchor, 1)
    return text.replace(anchor, anchor + content, 1)


def _apply_replace(item, text):
    edits = item.get("edits") or []
    if not edits and item.get("old") is not None:
        edits = [{"old": item["old"], "new": item["new"], "count": item.get("count", "one")}]
    if not edits:
        raise ItemError("replace 条目没有 edits")
    for edit in edits:
        old, new = edit["old"], edit["new"]
        mode = str(edit.get("count", "one"))
        if mode == "all":
            if text.count(old) < 1:
                raise ItemError("找不到要替换的原文：%r" % old[:80])
            text = text.replace(old, new)
        else:
            if text.count(old) != 1:
                raise ItemError(
                    "要替换的原文出现 %d 次（要求 1 次）：%r"
                    % (text.count(old), old[:80])
                )
            text = text.replace(old, new, 1)
    return text


def _apply_append(item, text):
    content = item["content"]
    if not text.endswith("\n"):
        text += "\n"
    return text + content


def apply_item(item):
    """把条目写进文件。返回 (changed, snapshot)。

    snapshot: {相对路径: 原内容 or None(原本不存在)}，用于失败时精确还原。
    """
    if _already_done(item):
        return False, {}

    target = ROOT / item["file"]
    snapshot = {}

    if item["kind"] == "new_file":
        snapshot[item["file"]] = None
        _write(target, item["content"])
    else:
        if not target.exists():
            raise ItemError("目标文件不存在：%s" % item["file"])
        before = _read(target)
        snapshot[item["file"]] = before
        if item["kind"] == "insert":
            after = _apply_insert(item, before)
        elif item["kind"] == "replace":
            after = _apply_replace(item, before)
        elif item["kind"] == "append":
            after = _apply_append(item, before)
        else:
            raise ItemError("不认识的 kind：%s" % item["kind"])
        if after == before:
            return False, {}
        _write(target, after)

    # 落盘后自检：marker 必须真的出现了
    marker = item.get("marker")
    if marker:
        if not target.exists() or marker not in _read(target):
            raise ItemError("写入后没找到 marker %r，可能替换串不匹配" % marker)
    return True, snapshot


def cleanliness(item):
    """改动【之前】采集：这个文件本身是不是干净的跟踪文件。

    只有在原本就干净的情况下，才允许用 `git checkout --` 回滚 ——
    否则会把用户自己还没提交的改动一起冲掉。
    """
    if item["kind"] == "new_file":
        return {}
    _, out = git("status", "--porcelain", "--", item["file"], check=False)
    if out.strip():
        return {}
    code, _ = git("ls-files", "--error-unmatch", "--", item["file"], check=False)
    return {item["file"]: code == 0}


def rollback(snapshot, clean_flags=None):
    """还原到改动前。原本干净的跟踪文件走 git checkout --，其余用内存快照。"""
    clean_flags = clean_flags or {}
    for rel, original in snapshot.items():
        target = ROOT / rel
        if original is None:                       # 本次新建的文件
            if target.exists():
                target.unlink()
                log("   回滚：删除新建文件 %s" % rel)
            continue
        if clean_flags.get(rel):
            code, _ = git("checkout", "--", rel, check=False)
            if code == 0:
                log("   回滚：git checkout -- %s" % rel)
                continue
            log("   git checkout -- %s 没成功，改用内存快照还原" % rel)
        _write(target, original)
        log("   回滚：内存快照还原 %s" % rel)


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #
def run_check(node):
    """跑 node check.js。返回 (ok, 摘要)。没有 node 时跳过并返回成功。"""
    if not node:
        return True, "找不到 node，跳过 check.js"
    if not (ROOT / "check.js").exists():
        return True, "没有 check.js，跳过"
    code, out = run([node, "check.js"], timeout=CHECK_TIMEOUT)
    keep = []
    for line in out.splitlines():
        line = line.strip()
        # 跳过 ──── 这类纯装饰线，只留人话
        if not line or set(line) <= set("─=-— "):
            continue
        keep.append(line)
    summary = " · ".join(keep[-2:]) if keep else "(无输出)"
    return code == 0, summary


def run_syntax_check(node, paths):
    """改动过的 .js 再单独过一遍 node --check。"""
    if not node:
        return True, "找不到 node，跳过语法检查"
    for rel in paths:
        if not rel.endswith(".js"):
            continue
        path = ROOT / rel
        if not path.exists():
            continue
        code, out = run([node, "--check", str(path)], timeout=60)
        if code != 0:
            return False, "%s 语法错误：%s" % (rel, out.strip()[:400])
    return True, "语法检查通过"


def verify(node, touched):
    ok, summary = run_syntax_check(node, touched)
    if not ok:
        return False, summary
    return run_check(node)


# --------------------------------------------------------------------------- #
# 提交
# --------------------------------------------------------------------------- #
def commit(item, files):
    subject = "每日一点：%s" % item["title"]
    lines = [
        item.get("note") or "",
        "",
        "改动：%s（%s）" % (item["file"], item["kind"]),
        "校验：node check.js 通过" if find_node() else "校验：本机没有 node，已跳过 check.js",
        "",
        "由 tools/daily_tune.py 按 tools/backlog.json 自动生成。",
    ]
    body = "\n".join([ln for ln in lines if ln is not None]).strip()
    git("add", "--", *files)
    git("commit", "-m", subject, "-m", body)
    _, out = git("log", "-1", "--format=%h %s")
    log("   已提交：%s" % out.strip())
    return subject


# --------------------------------------------------------------------------- #
# 巡检模式（backlog 做完了）
# --------------------------------------------------------------------------- #
STATS_JS = r"""
const fs = require('fs');
const src = fs.readFileSync('data.js', 'utf8');
const sandbox = {};
new Function('window', src + '\nreturn window.RECIPE_DB;')(sandbox);
const db = sandbox.RECIPE_DB;
const ings = db.ingredients || [];
const recipes = db.recipes || [];
const used = {};
let refs = 0;
recipes.forEach(function (r) {
  (r.ingredients || []).forEach(function (x) { refs++; used[x.id] = 1; });
});
const byCat = {}, byTag = {}, byCuisine = {};
ings.forEach(function (i) { byCat[i.category] = (byCat[i.category] || 0) + 1; });
recipes.forEach(function (r) {
  (r.tags || []).forEach(function (t) { byTag[t] = (byTag[t] || 0) + 1; });
  if (r.cuisine) byCuisine[r.cuisine] = (byCuisine[r.cuisine] || 0) + 1;
});
let stepMin = 99, stepMax = 0, charMin = 999, charMax = 0, timeMin = 1e9, timeMax = 0;
recipes.forEach(function (r) {
  const steps = r.steps || [];
  stepMin = Math.min(stepMin, steps.length);
  stepMax = Math.max(stepMax, steps.length);
  steps.forEach(function (s) {
    const n = Array.from(String(s)).length;
    charMin = Math.min(charMin, n);
    charMax = Math.max(charMax, n);
  });
  const t = Number(r.time) || 0;
  timeMin = Math.min(timeMin, t);
  timeMax = Math.max(timeMax, t);
});
let alias = 0, withAlias = 0;
ings.forEach(function (i) {
  const n = (i.alias || []).length;
  alias += n;
  if (n > 0) withAlias++;
});
const servings = [];
recipes.forEach(function (r) { if (servings.indexOf(r.servings) < 0) servings.push(r.servings); });
console.log(JSON.stringify({
  ingredients: ings.length,
  recipes: recipes.length,
  refs: refs,
  used: Object.keys(used).length,
  unused: ings.length - Object.keys(used).length,
  alias: alias,
  withAlias: withAlias,
  kb: Math.round(fs.statSync('data.js').size / 1024),
  byCat: byCat, byTag: byTag, byCuisine: byCuisine,
  stepMin: stepMin, stepMax: stepMax,
  charMin: charMin, charMax: charMax,
  timeMin: timeMin, timeMax: timeMax,
  servings: servings
}));
"""


def collect_stats(node):
    if not node:
        raise RuntimeError("巡检需要 node 来读 data.js，本机没找到")
    code, out = run([node, "-e", STATS_JS], timeout=60)
    if code != 0:
        raise RuntimeError("统计 data.js 失败：%s" % out.strip()[:600])
    return json.loads(out.strip().splitlines()[-1])


def rebuild_dist(line, counts, sep):
    """把「食材分类：蔬菜 53 · 肉禽 41 …」这类行按实际数据重排数字。

    保留 README 里原有的顺序与措辞，只更新数字；数据里新增的类别追加到末尾，
    已经为 0 的类别从这行里去掉。
    """
    if "：" not in line:
        return line
    head, body = line.split("：", 1)
    order = []
    for part in body.split(sep):
        part = part.strip()
        if not part:
            continue
        pieces = part.rsplit(" ", 1)
        if len(pieces) != 2 or not pieces[1].isdigit():
            continue
        label = pieces[0].strip()
        if label and label not in order:
            order.append(label)
    pairs = [(label, counts[label]) for label in order if label in counts]
    for label in sorted(counts, key=lambda k: (-counts[k], k)):
        if label not in order and counts[label]:
            pairs.append((label, counts[label]))
    return head + "：" + sep.join("%s %d" % (label, n) for label, n in pairs)


def patrol(node, push):
    log("backlog 已全部完成，进入巡检模式。")
    ok, summary = run_check(node)
    log("  check.js：%s" % summary)
    if not ok:
        log("  校验没通过，先别急着改 README —— 今天的巡检跳过。")
        return 0

    stats = collect_stats(node)
    log(
        "  data.js 实测：食材 %d · 菜谱 %d · 引用 %d · 用到 %d · 未用 %d · 别名 %d 条"
        % (
            stats["ingredients"],
            stats["recipes"],
            stats["refs"],
            stats["used"],
            stats["unused"],
            stats["alias"],
        )
    )

    text = README_PATH.read_text(encoding="utf-8") if README_PATH.exists() else ""
    if not text:
        log("  找不到 README.md，无事可做。")
        return 0
    original = text
    changed = []

    def sub(pattern, replacement, label, flags=0):
        nonlocal text
        new_text, hits = re.subn(pattern, replacement, text, count=1, flags=flags)
        if hits:
            if new_text != text:
                changed.append(label)
            text = new_text

    def sub_line(pattern, builder, label, sep=" · "):
        nonlocal text
        match = re.search(pattern, text, flags=re.MULTILINE)
        if not match:
            return
        new_line = builder(match.group(0))
        if new_line != match.group(0):
            text = text[: match.start()] + new_line + text[match.end() :]
            changed.append(label)

    sub(
        r"内联数据：(\d+) 食材 \+ (\d+) 菜谱（≈(\d+) KB）",
        "内联数据：%d 食材 + %d 菜谱（≈%d KB）"
        % (stats["ingredients"], stats["recipes"], stats["kb"]),
        "data.js 体积",
    )
    sub(
        r"（(\d+) 种全部有别名，共 (\d+) 条）",
        "（%d 种全部有别名，共 %d 条）" % (stats["withAlias"], stats["alias"]),
        "别名条数",
    )
    sub(
        r"\| 食材 \| \*\*(\d+) 种\*\* \|",
        "| 食材 | **%d 种** |" % stats["ingredients"],
        "食材数",
    )
    sub(
        r"\| 菜谱 \| \*\*(\d+) 道\*\*",
        "| 菜谱 | **%d 道**" % stats["recipes"],
        "菜谱数",
    )
    sub(
        r"\| 菜谱-食材引用 \| (\d+) 条 \|",
        "| 菜谱-食材引用 | %d 条 |" % stats["refs"],
        "引用条数",
    )
    sub(
        r"\| 被菜谱用到的食材 \| (\d+) 种（其余 (\d+) 种",
        "| 被菜谱用到的食材 | %d 种（其余 %d 种" % (stats["used"], stats["unused"]),
        "用到/未用食材",
    )
    sub_line(r"^食材分类：.*$", lambda ln: rebuild_dist(ln, stats["byCat"], " · "), "食材分类")
    sub_line(r"^菜谱标签：.*$", lambda ln: rebuild_dist(ln, stats["byTag"], " · "), "菜谱标签")
    sub_line(r"^菜系：.*$", lambda ln: rebuild_dist(ln, stats["byCuisine"], " · "), "菜系分布")
    sub(
        r"食材 (\d+) 种 · 菜谱 (\d+) 道 · 食材引用 (\d+) 次",
        "食材 %d 种 · 菜谱 %d 道 · 食材引用 %d 次"
        % (stats["ingredients"], stats["recipes"], stats["refs"]),
        "最近一次结果-总量",
    )
    sub_line(r"^分类：.*$", lambda ln: rebuild_dist(ln, stats["byCat"], " / "), "最近一次结果-分类")
    sub(
        r"未被任何菜谱用到：(\d+) 种",
        "未被任何菜谱用到：%d 种" % stats["unused"],
        "未用食材",
    )
    sub(
        r"\*\*(\d+) 种食材暂无对应菜谱\*\*：食材库刻意比菜谱宽（(\d+) vs 用到 (\d+)）",
        "**%d 种食材暂无对应菜谱**：食材库刻意比菜谱宽（%d vs 用到 %d）"
        % (stats["unused"], stats["ingredients"], stats["used"]),
        "已知局限-未用食材",
    )
    sub(
        r"`steps`：(\d+)–(\d+) 步，每步 (\d+)–(\d+) 个汉字",
        "`steps`：%d–%d 步，每步 %d–%d 个汉字"
        % (stats["stepMin"], stats["stepMax"], stats["charMin"], stats["charMax"]),
        "步骤数与字数",
    )
    sub(
        r"烹饪时长 (\d+)–(\d+) 分钟",
        "烹饪时长 %d–%d 分钟" % (stats["timeMin"], stats["timeMax"]),
        "烹饪时长",
    )

    if text == original:
        log("  巡检通过：README 里的数字和 data.js 完全一致，今天不提交。")
        return 0

    README_PATH.write_text(text, encoding="utf-8")
    log("  README 数字过时：%s" % "、".join(dict.fromkeys(changed)))
    subject = "每日巡检：更新统计数字"
    body = "\n".join(
        [
            "check.js 通过，但 README 里写的数字已经和 data.js 对不上了。",
            "本次更新：%s。" % "、".join(dict.fromkeys(changed)),
            "实测：食材 %d · 菜谱 %d · 引用 %d · 未用 %d。"
            % (stats["ingredients"], stats["recipes"], stats["refs"], stats["unused"]),
            "",
            "由 tools/daily_tune.py 巡检模式自动生成。",
        ]
    )
    state = load_state()
    state["runs"].append(
        {"date": today(), "id": "patrol", "result": "commit", "title": subject}
    )
    save_state(state)
    files = ["README.md", "tools/applied.json"]
    git("add", "--", *files)
    git("commit", "-m", subject, "-m", body)
    _, out = git("log", "-1", "--format=%h %s")
    log("   已提交：%s" % out.strip())
    if push:
        code, out = git("push", check=False)
        log("   git push：%s" % ("成功" if code == 0 else out.strip()[:400]))
        if code != 0:
            return 1
    return 0


# --------------------------------------------------------------------------- #
# dry-run
# --------------------------------------------------------------------------- #
def describe(item):
    kind = item["kind"]
    if kind == "new_file":
        return "新增文件 %s" % item["file"]
    if kind == "insert":
        where = "前面" if item.get("before") else "后面"
        return "在 %s 里插到 %s 的%s" % (item["file"], repr(item["anchor"])[:60], where)
    if kind == "append":
        return "在 %s 末尾追加一段" % item["file"]
    edits = item.get("edits") or []
    if len(edits) == 1:
        return "在 %s 里替换 1 处" % item["file"]
    return "在 %s 里替换 %d 处" % (item["file"], len(edits))


def dry_run(backlog, state, node):
    done, total = backlog_progress(backlog, state)
    log("仓库：%s" % ROOT)
    log("backlog：%d 项，已完成 %d 项，剩 %d 项" % (total, done, total - done))
    log(
        "node：%s"
        % (node or "没找到（会跳过 check.js 校验）")
    )
    if state["failed"]:
        log("失败的条目：%s" % "、".join(sorted(state["failed"].keys())))
    item = pick_next(backlog, state)
    if item is None:
        log("")
        log("今天要做的：backlog 已经全部完成 → 巡检模式")
        log("将执行：node check.js，然后核对 README 里的统计数字；不一致才改 README 并提交。")
        return 0
    log("")
    log("今天要做的：#%s  %s" % (item["id"], item["title"]))
    log("将改动的文件：%s" % item["file"])
    log("怎么改：%s" % describe(item))
    if item.get("note"):
        log("为什么：%s" % item["note"])
    log("做完会跑：node check.js（失败就回滚、标记 failed、换下一项）")
    log("提交信息：每日一点：%s" % item["title"])
    log("")
    log("（--dry-run：没有写入任何文件）")
    return 0


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main(argv):
    parser = argparse.ArgumentParser(description="小锅菜谱每日一点")
    parser.add_argument("--dry-run", action="store_true", help="只打印今天要做什么")
    parser.add_argument("--push", action="store_true", help="提交后 git push")
    parser.add_argument("--retry-failed", action="store_true", help="把 failed 的条目放回队列")
    args = parser.parse_args(argv)

    if not BACKLOG_PATH.exists():
        log("找不到 %s" % BACKLOG_PATH)
        return 1

    node = find_node()
    backlog = load_backlog()
    state = load_state()

    if args.retry_failed and state["failed"]:
        log("放回失败队列：%s" % "、".join(sorted(state["failed"].keys())))
        for key in list(state["failed"].keys()):
            state["failed"].pop(key, None)
        save_state(state)

    if args.dry_run:
        return dry_run(backlog, state, node)

    log("== 每日一点 %s ==" % today())
    log("仓库：%s" % ROOT)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        item = pick_next(backlog, state)
        if item is None:
            log("")
            log("-- backlog 已全部完成 --")
            return patrol(node, args.push)

        log("")
        log("[%d/%d] %s" % (attempt, MAX_ATTEMPTS, item["id"]))
        log("  %s → %s" % (item["title"], describe(item)))

        snapshot = {}
        clean_flags = cleanliness(item)
        try:
            changed, snapshot = apply_item(item)
        except ItemError as exc:
            log("  跳过：%s" % exc)
            if snapshot:
                rollback(snapshot, clean_flags)
            state["failed"][item["id"]] = {"date": today(), "reason": str(exc)}
            state["runs"].append(
                {"date": today(), "id": item["id"], "result": "error", "title": item["title"]}
            )
            save_state(state)
            continue

        if not changed:
            log("  这一项以前已经改过了（幂等跳过），记进 applied 继续下一项。")
            state["applied"].append(item["id"])
            state["runs"].append(
                {"date": today(), "id": item["id"], "result": "noop", "title": item["title"]}
            )
            save_state(state)
            continue

        ok, summary = verify(node, list(snapshot.keys()))
        log("  校验：%s" % summary)

        if not ok:
            log("  校验没过，回滚这一项，标记 failed，换下一项。")
            rollback(snapshot, clean_flags)
            state["failed"][item["id"]] = {"date": today(), "reason": summary[:500]}
            state["runs"].append(
                {"date": today(), "id": item["id"], "result": "failed", "title": item["title"]}
            )
            save_state(state)
            continue

        state["applied"].append(item["id"])
        state["runs"].append(
            {"date": today(), "id": item["id"], "result": "applied", "title": item["title"]}
        )
        save_state(state)

        files = sorted(snapshot.keys()) + ["tools/applied.json"]
        subject = commit(item, files)
        if args.push:
            code, out = git("push", check=False)
            if code == 0:
                log("   git push：成功")
            else:
                log("   git push 失败：%s" % out.strip()[:400])
                log("   提交还在本地，下次运行会一起推。")
                return 1
        done, total = backlog_progress(backlog, state)
        log("  进度：%d/%d（%s）" % (done, total, subject))
        return 0

    log("")
    log("连续 %d 项都没改成（看上面的 reason），今天不提交。请手动检查 backlog。" % MAX_ATTEMPTS)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:                                   # noqa: BLE001
        log("!! 运行出错，未完成：")
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)
