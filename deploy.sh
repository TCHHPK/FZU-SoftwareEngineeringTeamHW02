#!/usr/bin/env bash
# 一键部署脚本（Ubuntu 22.04 / 24.04）
#
# 用法（在服务器上执行，需要 root 权限）：
#     bash deploy.sh
#
# 它会完成：
#   1. 安装系统依赖与 Python 3.12
#   2. 创建 venv 并安装 requirements.txt
#   3. 检查 .env（缺失则从 .env.example 生成并提示填写密钥）
#   4. 初始化数据库
#   5. 注册 systemd 服务：开机自启、崩溃自动重启
#   6. 放行本机防火墙（云厂商安全组需另行在控制台放行）
#   7. 打印访问地址与自检命令
#
# 幂等：可以重复执行，不会重复安装或覆盖已有 .env 与数据库。

set -euo pipefail

APP_NAME="course-note-agent"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
PORT="${APP_PORT:-8000}"
PY_BIN="python3.12"

log()  { printf '\033[1;32m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\033[1;33m[警告]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[失败]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "请用 root 执行：sudo bash deploy.sh"

# --------------------------------------------------------------------------
# 1. 系统依赖与 Python 3.12
# --------------------------------------------------------------------------
log "安装系统依赖 ..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl ca-certificates \
    build-essential libffi-dev >/dev/null

if ! command -v "$PY_BIN" >/dev/null 2>&1; then
    log "$PY_BIN 不存在，尝试安装 ..."
    apt-get install -y -qq software-properties-common >/dev/null
    add-apt-repository -y ppa:deadsnakes/ppa >/dev/null 2>&1 || true
    apt-get update -qq
    if ! apt-get install -y -qq "$PY_BIN" "${PY_BIN}-venv" >/dev/null 2>&1; then
        warn "无法安装 $PY_BIN，回退到系统自带 python3（版本可能低于 3.12）"
        PY_BIN="python3"
    fi
fi
log "使用解释器：$($PY_BIN --version 2>&1)"

# --------------------------------------------------------------------------
# 2. 虚拟环境与依赖
# --------------------------------------------------------------------------
log "创建虚拟环境并安装依赖（首次约需 1~3 分钟）..."
cd "$APP_DIR"
[[ -d .venv ]] || "$PY_BIN" -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt
log "依赖安装完成"

# --------------------------------------------------------------------------
# 3. 配置文件
# --------------------------------------------------------------------------
if [[ ! -f .env ]]; then
    cp .env.example .env
    # 生成随机 SECRET_KEY，避免上线还用默认值
    SECRET="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env
    sed -i "s|^APP_PORT=.*|APP_PORT=${PORT}|" .env
    chmod 600 .env
    warn "已生成 .env（SECRET_KEY 已随机化）。"
    warn "请编辑 .env 填入 LLM_API_KEYS，然后重新运行本脚本或重启服务："
    warn "    nano ${APP_DIR}/.env"
    NEED_KEY=1
else
    chmod 600 .env
    log "沿用已有 .env"
    NEED_KEY=0
    if ! grep -qE '^LLM_API_KEYS=sk-[A-Za-z0-9]' .env; then
        NEED_KEY=1
    fi
fi

# --------------------------------------------------------------------------
# 4. 初始化数据库
# --------------------------------------------------------------------------
log "初始化数据库 ..."
./.venv/bin/python -m scripts.init_db
log "自检（不需要模型密钥）..."
./.venv/bin/python tests/test_contracts.py | tail -2

# --------------------------------------------------------------------------
# 5. systemd 服务
# --------------------------------------------------------------------------
log "注册 systemd 服务 ..."
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=课程课件笔记整理 Agent（FastAPI）
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
Restart=always
RestartSec=3
StandardOutput=append:${APP_DIR}/logs/service.log
StandardError=append:${APP_DIR}/logs/service.log

[Install]
WantedBy=multi-user.target
EOF

mkdir -p logs
systemctl daemon-reload
systemctl enable "$APP_NAME" >/dev/null
systemctl restart "$APP_NAME"
sleep 3

# --------------------------------------------------------------------------
# 6. 本机防火墙
# --------------------------------------------------------------------------
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow "${PORT}/tcp" >/dev/null || true
    log "已放行 ufw ${PORT}/tcp"
fi

# --------------------------------------------------------------------------
# 7. 结果
# --------------------------------------------------------------------------
PUBLIC_IP="$(curl -s --max-time 5 https://api.ipify.org || echo '<你的公网IP>')"
echo
echo "======================================================================"
if systemctl is-active --quiet "$APP_NAME"; then
    log "服务已启动 ✅"
else
    die "服务启动失败，查看日志：journalctl -u ${APP_NAME} -n 50"
fi
echo "  访问地址 : http://${PUBLIC_IP}:${PORT}"
echo "  接口文档 : http://${PUBLIC_IP}:${PORT}/docs"
echo "  健康检查 : http://${PUBLIC_IP}:${PORT}/api/health"
echo
echo "  常用命令："
echo "    systemctl status ${APP_NAME}     # 查看状态"
echo "    systemctl restart ${APP_NAME}    # 重启（改完 .env 后执行）"
echo "    tail -f ${APP_DIR}/logs/service.log   # 看实时日志"
echo
if [[ "${NEED_KEY}" == "1" ]]; then
    warn "还没配置 LLM_API_KEYS：现在只能上传解析、不能生成笔记。"
    warn "填好后执行：systemctl restart ${APP_NAME}"
fi
warn "别忘了在云厂商控制台的『安全组/防火墙』放行 TCP ${PORT}，否则外网访问不了。"
echo "======================================================================"
