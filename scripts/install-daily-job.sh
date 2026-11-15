#!/bin/bash
# 装上「每天 10:30 给菜谱做一个小优化」的 launchd 任务。
#
#   bash scripts/install-daily-job.sh          # 安装/重装
#   bash scripts/uninstall-daily-job.sh        # 卸载
#
# 装完不会立刻跑第一次 —— 想手动试运行看 scripts/install 的结尾提示。
set -euo pipefail

LABEL="com.hufayang.recipe-daily-tune"
PLIST_NAME="${LABEL}.plist"
SRC_PLIST="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/${PLIST_NAME}"
AGENT_DIR="${HOME}/Library/LaunchAgents"
DST_PLIST="${AGENT_DIR}/${PLIST_NAME}"
LOG_DIR="${HOME}/Library/Logs"
LOG_FILE="${LOG_DIR}/recipe-daily-tune.log"
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"

# 仓库根（scripts/ 的上一级），plist 里写死的是这个路径
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_REPO="/Users/apple/Projects/recipe-app"

say() { printf '%s\n' "$*"; }
die() { printf '错误：%s\n' "$*" >&2; exit 1; }

[ -f "${SRC_PLIST}" ] || die "找不到 plist：${SRC_PLIST}"
[ -f "${REPO_ROOT}/tools/daily_tune.py" ] || die "找不到 ${REPO_ROOT}/tools/daily_tune.py"
[ -f "${REPO_ROOT}/tools/backlog.json" ] || die "找不到 ${REPO_ROOT}/tools/backlog.json"
[ -x /usr/bin/python3 ] || die "/usr/bin/python3 不存在"

say "仓库：${REPO_ROOT}"
say "任务：${LABEL}（每天 10:30）"
say "日志：${LOG_FILE}"
say ""

# 1) 先卸载旧的（没装过会报错，忽略即可）
say "==> 卸载已存在的同名任务（如果有）"
launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
rm -f "${DST_PLIST}"

# 2) 准备日志目录
mkdir -p "${LOG_DIR}" "${AGENT_DIR}" || die "创建 ${LOG_DIR} / ${AGENT_DIR} 失败"

# 3) 拷 plist；仓库不在默认路径时把路径改成本机实际路径
if [ "${REPO_ROOT}" = "${PLIST_REPO}" ]; then
  cp "${SRC_PLIST}" "${DST_PLIST}"
else
  say "    仓库不在 ${PLIST_REPO}，把 plist 里的路径改写成 ${REPO_ROOT}"
  sed "s|${PLIST_REPO}|${REPO_ROOT}|g" "${SRC_PLIST}" > "${DST_PLIST}"
fi
chmod 644 "${DST_PLIST}"
plutil -lint "${DST_PLIST}" >/dev/null || die "plist 语法不合法：${DST_PLIST}"

# 4) 注册
say "==> launchctl bootstrap ${DOMAIN}"
if ! launchctl bootstrap "${DOMAIN}" "${DST_PLIST}"; then
  die "bootstrap 失败。先看看 launchctl print ${DOMAIN}/${LABEL} 的输出，或 /var/log/system.log"
fi

# 5) 验证
say "==> launchctl print ${DOMAIN}/${LABEL}"
if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  launchctl print "${DOMAIN}/${LABEL}" | grep -E "state|path|program|runs|last exit" | sed 's/^/    /'
  say ""
  say "装好了。明天 10:30 会自己跑；想现在试一次："
  say "    /usr/bin/python3 ${REPO_ROOT}/tools/daily_tune.py --dry-run   # 只看今天会改什么"
  say "    /usr/bin/python3 ${REPO_ROOT}/tools/daily_tune.py             # 真的改+提交（不 push）"
  say "    /usr/bin/python3 ${REPO_ROOT}/tools/daily_tune.py --push      # 和定时任务一样"
  say "    tail -f ${LOG_FILE}                                           # 看日志"
  say "    bash ${REPO_ROOT}/scripts/uninstall-daily-job.sh               # 卸载"
  say ""
  say "注意：手动 kickstart 也会消耗一个 backlog 条目（launchd 不会去重）。"
  say "    launchctl kickstart -p ${DOMAIN}/${LABEL}                     # 立即跑一次（可选）"
else
  die "bootstrap 之后 launchctl print 读不到这个任务，安装未生效"
fi
