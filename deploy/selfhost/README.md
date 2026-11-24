<!-- Copyright 2026 radish40. SPDX-License-Identifier: AGPL-3.0-only -->

# Radish Chat 运维与发布

维护仓库为 `radish40/element-web`，`main` 从上游 `v1.12.35` 建立。
本目录记录本次部署的修改。上游版权和许可证保留在仓库中。

## 线上服务

| 用途 | 地址或位置 |
| --- | --- |
| Element Web | https://chat.547626.xyz |
| Synapse API | https://matrix.547626.xyz |
| Matrix 用户 ID | `@用户名:547626.xyz` |
| VPS | `opc@132.226.127.9`，SSH 22 |
| 静态版本 | `/opt/radish-chat/releases/<完整提交 SHA>` |
| 当前版本 | `/opt/radish-chat/current` |
| 服务端配置、签名密钥和媒体 | `/opt/radish-chat/data/synapse` |
| PostgreSQL 数据 | `/opt/radish-chat/data/postgres` |
| 服务端私有配置 | `/opt/radish-chat/private` |

## 日常开发

```sh
git clone https://github.com/radish40/element-web.git
cd element-web
git remote add upstream https://github.com/element-hq/element-web.git
npm install --global pnpm@12.14.0
pnpm install --frozen-lockfile
cp deploy/selfhost/config.json apps/web/config.json
pnpm --dir apps/web start
```

使用 Node.js 24。上游开发文档在 `developer_guide.md`，代理规则在 `AGENTS.md`。
客户端代码主要在 `apps/web`，可复用界面在 `packages/shared-components`。
站点配置在本目录的 `config.json`。Synapse 目前使用固定摘要的官方 ARM64 镜像。

## 自动发布

推送 `main` 后，GitHub Actions 的 `Publish Radish Chat` 会安装锁定依赖、检查部署脚本、
从 fork 源码构建客户端、上传制品，通过 SSH 把制品送到服务器，检查后原子切换 `current`。
Pull Request 只构建验证。数据库和用户文件独立持久化。

仓库的 `CHAT_DEPLOY_KEY` 和 `CHAT_KNOWN_HOSTS` 已配置在 Actions secrets 中。
SSH 发布账号被限制为 `deploy <SHA>` 和 `rollback <SHA>` 两个命令。
每个线上版本的 `/revision.json` 包含源码提交和源码地址。

## 回滚

在 Actions 中选择 `Publish Radish Chat`，点 Run workflow，把服务器已有版本的完整 SHA
填入 `rollback_commit`。留空会重新构建发布当前 `main`。

服务器管理员也可以执行以下命令。

```sh
sudo /usr/local/libexec/radish-chat/publish.py rollback <完整提交SHA>
```

这是客户端回滚。升级 Synapse 或 PostgreSQL 时，应先执行备份，核对上游迁移说明，
再更新 `bootstrap.sh` 中的镜像摘要并应用。数据库迁移后按相应版本恢复备份。

## 账号

本次选择关闭公开注册，由管理员创建账号。首个管理员为 `radish`，首次登录后修改密码，
并在客户端设置中配置加密恢复方式。

创建新账号时，服务器执行交互命令，密码在终端输入。

```sh
sudo podman exec -it radish-chat-synapse register_new_matrix_user \
    -c /data/homeserver.yaml http://127.0.0.1:8008
```

## 后端管理与备份

```sh
sudo systemctl status radish-chat-synapse radish-chat-postgres
sudo journalctl -u radish-chat-synapse -n 100
sudo systemctl start radish-chat-backup.service
sudo systemctl list-timers radish-chat-backup.timer certbot-renew.timer
```

每天 UTC 19 时执行本机备份，保留最近约七天。备份包含 PostgreSQL dump、
配置、签名密钥和媒体文件，位于 `/opt/radish-chat/backups`，仅 root 可读。
定期把备份复制到独立存储。客户端发布不需要停后端。

恢复时先停止 Synapse，使用备份中的 dump 恢复 PostgreSQL，再恢复同批配置和媒体，
确认文件归属为 UID/GID 991 后启动。备份为在线快照，备份期间新上传的媒体可能需要从
下一批备份补齐。首次交付会实际验证数据库 dump 可以恢复到临时数据库。

## 首次安装与配置更新

把本目录复制到服务器，在服务器以 root 运行 `bootstrap.sh`。
它会安装固定版本的服务、持久化数据、受限发布账号和备份定时器。
第一次配置中生成的服务端密钥会被保留。修改后端配置时会重新生成配置文件，
因此相关定制应进入脚本或单独的配置管理。

`nginx.conf` 安装为 `/etc/nginx/conf.d/radish-chat.conf`。
证书名称为 `radish-chat`，覆盖 `chat.547626.xyz` 和 `matrix.547626.xyz`。
根域名的 `/.well-known/matrix/client`、`/.well-known/matrix/server` 委派到 matrix 子域名。
当前部署范围包含文字、群聊、图片和文件。语音视频通话的 Element Call/LiveKit 服务单独配置。
