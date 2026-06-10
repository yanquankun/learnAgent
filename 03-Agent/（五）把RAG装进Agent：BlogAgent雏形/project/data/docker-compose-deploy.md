---
title: 用 Docker Compose 一键部署 Postgres 和 Redis
slug: docker-compose-deploy
tags: [docker, devops, database]
createdAt: 2025-10-21
---

## 为什么用 Docker Compose

在服务器上手动安装数据库，版本管理混乱、迁移困难、卸载留垃圾。
Docker Compose 用一个 yaml 文件声明所有服务，一条命令启动整套环境，
删除时也干干净净，是个人服务器部署的最佳实践。

## 编写 docker-compose.yml

核心思路是声明两个服务：postgres 和 redis。
postgres 服务要注意三点：用环境变量设置初始密码，
把数据目录挂载到宿主机卷（volume）防止容器删除后数据丢失，
以及只把端口绑定到 127.0.0.1 避免数据库直接暴露公网。

redis 服务类似，重点是开启 appendonly 持久化，
并用 requirepass 设置访问密码。

## 常用运维命令

docker compose up -d 后台启动所有服务。
docker compose ps 查看服务状态。
docker compose logs -f postgres 实时查看某个服务的日志。
docker compose down 停止并删除容器（卷会保留，数据不丢失）。

## 安全建议

第一，所有密码用 .env 文件管理，不要写死在 yaml 里，并把 .env 加入 gitignore。
第二，数据库端口永远不要绑定到 0.0.0.0，应用通过 Docker 内部网络访问。
第三，定期用 pg_dump 配合 cron 做自动备份，备份文件传到对象存储。
