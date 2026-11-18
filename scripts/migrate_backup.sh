#!/usr/bin/env bash
# 迁移打包脚本：在【旧服务器】上执行，产出一个可直接搬到新服务器的压缩包。
#
# 用法（root 权限）：
#     bash scripts/migrate_backup.sh
#
# 产出：/root/course-note-agent-migrate-<日期>.tar.gz
#
# 打包内容（只搬"变了会出事"的东西）：
#     app/  scripts/  tests/  requirements.txt  deploy.sh  .env  storage/
# 排除：
#     .venv/（新机器重新装，跨机器不可用）
#     __pycache__/  *.pyc  logs/（日志不必搬）
#
# 为什么要先停服务：
#     SQLite 运行中可能有未落盘的 WAL 数据，热拷贝可能拿到不一致的库。
#     停 3 秒再拷，最稳。脚本结束会自动把服务拉起来。

set -euo pipefail

APP_NAME="course-note-agent"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d-%H%M)"
OUT="/root/${APP_NAME}-migrate-${STAMP}.tar.gz"

log()  { printf '\033[1;32m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\033[1;33m[警告]\033[0m %s\n' "$*"; }

cd "$APP_DIR"

# ---- 1. 检查关键文件 ----
[[ -f .env ]] || { echo "[失败] 当前目录没有 .env，路径不对？当前：$APP_DIR"; exit 1; }
log "项目目录：$APP_DIR"

# ---- 2. 停服务，保证数据库一致 ----
WAS_RUNNING=0
if systemctl is-active --quiet "$APP_NAME" 2>/dev/null; then
    WAS_RUNNING=1
    log "暂停服务（保证 SQLite 数据一致）..."
    systemctl stop "$APP_NAME"
fi
# 无论后面成功失败，退出时都把服务拉回来
cleanup() {
    if [[ "$WAS_RUNNING" == "1" ]]; then
        systemctl start "$APP_NAME" 2>/dev/null || warn "自动拉起失败，请手动执行 systemctl start $APP_NAME"
    fi
}
trap cleanup EXIT

# ---- 3. 打包 ----
log "打包中 ..."
tar czf "$OUT" \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='logs' \
    --exclude='storage/*.db-wal' \
    --exclude='storage/*.db-shm' \
    . 2>/dev/null || true

# tar 会把 . 打进去，解压时用 -C 指定目录即可
SIZE="$(du -h "$OUT" | cut -f1)"
SHA="$(sha256sum "$OUT" | cut -d' ' -f1)"

log "打包完成：$OUT"
log "大小：$SIZE"
log "SHA256：$SHA"
echo
echo "----------------------------------------------------------------------"
echo "下一步："
echo "  1) 把包下载到你电脑（在【你自己电脑】上执行，不是在服务器上）："
echo "       scp root@<旧服务器IP>:$OUT ./"
echo "  2) 上传到新服务器："
echo "       scp $(basename "$OUT") root@<新服务器IP>:/root/"
echo "  3) 在新服务器上部署："
echo "       mkdir -p /root/course-note-agent"
echo "       tar xzf /root/$(basename "$OUT") -C /root/course-note-agent"
echo "       cd /root/course-note-agent && bash deploy.sh"
echo "  4) 控制台放行 TCP 8000（安全组入方向）"
echo "----------------------------------------------------------------------"
