#!/usr/bin/env bash
# scripts/setup_pi_ssh.sh
# 本机生成 SSH key 并推送到 Pi, 之后免密登录
# 之后所有 ssh/scp/rsync 都不再需要密码
#
# 用法: PI_HOST=192.168.88.102 bash scripts/setup_pi_ssh.sh
#
# 原理: 用 expect 输一次密码把本机公钥写到 Pi 的 ~/.ssh/authorized_keys

set -e
PI_HOST="${PI_HOST:-}"
PI_USER="${PI_USER:-youfu}"
PI_PORT="${PI_PORT:-22}"

if [[ -z "${PI_HOST}" ]]; then
    read -r -p "[?] Pi IP: " PI_HOST
fi

KEY_PATH="$HOME/.ssh/id_ed25519"
if [[ ! -f "${KEY_PATH}" ]]; then
    echo "[*] 生成 SSH key: ${KEY_PATH}"
    ssh-keygen -t ed25519 -N "" -f "${KEY_PATH}"
fi

PUB_KEY="$(cat ${KEY_PATH}.pub)"
echo "[*] 公钥:"
echo "    ${PUB_KEY:0:60}..."

read -r -s -p "[?] Pi 密码 (用一次即可, 之后免密): " PI_PASS
echo

# 推公钥
cat > /tmp/setup_ssh.exp <<EXP
set timeout 20
spawn ssh-copy-id -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p ${PI_PORT} ${PI_USER}@${PI_HOST}
expect {
    -re ".*assword.*" { send "${PI_PASS}\r"; exp_continue }
    eof
}
EXP
expect /tmp/setup_ssh.exp

# 验证免密
echo
echo "[*] 验证免密登录..."
if ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p ${PI_PORT} ${PI_USER}@${PI_HOST} "echo KEY_AUTH_OK_$(whoami)"; then
    echo "[+] 免密登录成功, 之后 deploy_pi.sh 不用再传密码"
else
    echo "[-] 免密登录失败, 看看 ssh-copy-id 哪里报错"
fi