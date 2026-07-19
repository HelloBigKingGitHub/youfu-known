# 备份与恢复 (Backup & Restore)

`youfu-known` 的所有持久数据都放在 `storage/` 下:

- `storage/knowledge_base.sqlite3` —— 知识库 / 文档 / 聊天历史的元数据
- `storage/chroma/`               —— 向量索引 (Chroma PersistentClient)
- `storage/uploads/{kb_id}/`      —— 用户上传的原始文件

任何一处丢失都会让对应 KB 不可用。本目录的脚本负责把这些数据**周期备份**到 `backups/`, 并支持**手动恢复**。

## 一键使用

```bash
# 立即备份
bash scripts/backup.sh

# 列出已有备份
ls -lh backups/

# 恢复最近一次
bash scripts/restore.sh --latest

# 恢复指定备份
bash scripts/restore.sh backups/backup-20260101-030000.tar.gz
```

## 备份策略

脚本默认:

- 输出目录: `<install>/backups/`
  - 默认 `/home/youfu/youfu-known/backups/`
  - 通过环境变量 `YOUFU_BACKUP_DIR` 覆盖
- 文件名: `backup-YYYYMMDD-HHMMSS.tar.gz`
- 保留策略:
  - **最近 7 天**的所有备份 (通过 `YOUFU_KEEP_DAILY` 调整)
  - **最近 4 个周日**的备份额外保留 (通过 `YOUFU_KEEP_WEEKLY` 调整)
- 排除: `storage/chroma-tmp/` (Chroma 临时目录, 可重新生成)

示例: 一周内每天都跑 → 保留 7 个 `backup-*.tar.gz`; 跨周时旧的非周日备份自动清理, 周日的最多留 4 份。

## systemd 定时 (可选)

`scripts/backup.timer` 定义了 systemd timer, 默认每日 03:00 触发:

```ini
[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
```

启用方式:

```bash
# 1. 替换模板 (USER / GROUP / INSTALL_DIR / BACKUP_DIR)
sed -e "s|@USER@|$(id -un)|g" \
    -e "s|@GROUP@|$(id -gn)|g" \
    -e "s|@INSTALL_DIR@|/home/youfu/youfu-known|g" \
    -e "s|@BACKUP_DIR@|/home/youfu/youfu-known/backups|g" \
    scripts/backup.service > /tmp/youfu-backup.service
sudo cp /tmp/youfu-backup.service /etc/systemd/system/youfu-backup.service
sudo cp scripts/backup.timer /etc/systemd/system/youfu-backup.timer

# 2. 启用 + 立即跑一次验证
sudo systemctl daemon-reload
sudo systemctl enable --now youfu-backup.timer
sudo systemctl start youfu-backup.service      # 手动触发, 看日志

# 3. 查看日志
journalctl -u youfu-backup.service -n 50
systemctl list-timers youfu-backup.timer
```

## 跨机备份 (可选)

把 `backups/` 推到远端即可:

```bash
# 例: 用 restic / rsync / rclone 推送到异地
rclone sync backups/ remote:youfu-known-backups/
```

## 故障演练

模拟 "误删 storage/" 后的恢复流程:

```bash
bash scripts/stop.sh
rm -rf storage/
bash scripts/restore.sh --latest
bash scripts/start.sh

# 验证: KB / 文档 / 聊天历史应全部回来
curl http://127.0.0.1:8000/api/kbs
```

## 注意事项

- 备份是 **冷备份**: 脚本未与服务联动, 跑备份时如果服务在写 SQLite/Chroma, 极端情况可能拿到一致状态略差的快照。对个人知识库场景 (读写频率低) 完全够用; 高一致性需求建议先 `bash scripts/stop.sh` 再备份。
- 备份只保留在本地, **请把 `backups/` 加入异地同步** (crontab / restic / rsync …), 否则磁盘故障仍会丢数据。
- 恢复会**覆盖**当前 `storage/`, 恢复前旧数据会自动快照到 `/tmp/youfu-known-storage.<timestamp>/`, 万一出问题可以手动回滚。