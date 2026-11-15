#!/bin/bash
# 卸载「每天 10:30 给菜谱做一个小优化」的 launchd 任务。
# 只动 LaunchAgents 里的这一个 plist，不碰仓库、不碰日志。
set -euo pipefail

LABEL="com.hufayang.recipe-daily-tune"
PLIST_NAME="${LABEL}.plist"
AGENT_DIR="${HOME}/Library/LaunchAgents"
DST_PLIST="${AGENT_DIR}/${PLIST_NAME}"
LOG_FILE="${HOME}/Library/Logs/recipe-daily-tune.log"
DOMAIN="gui/$(id -u)"

say() { printf '%s\n' "$*"; }

say "==> launchctl bootout ${DOMAIN}/${LABEL}"
if launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null; then
  say "    已卸载运行中的任务"
else
  say "    当前没有加载这个任务（可能是第一次卸载，忽略）"
fi

if [ -f "${DST_PLIST}" ]; then
  rm -f "${DST_PLIST}"
  say "    已删除 ${DST_PLIST}"
else
  say "    ${DST_PLIST} 本来就不存在"
fi

if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  say ""
  say "注意：launchctl print 还能读到这个 Label，可能是缓存。过一分钟再看，"
  say "      或者 launchctl bootout ${DOMAIN}/${LABEL} 再试一次。"
else
  say ""
  say "确认已卸载：launchctl print ${DOMAIN}/${LABEL} 读不到了。"
fi

say ""
say "日志留在 ${LOG_FILE}（没删，想清就 rm 它）。"
say "想彻底恢复干净：git log 里搜「每日一点：」把你不想留的提交 revert 掉。"
