# Grok2API Docker CLI

本文档说明如何使用仓库内的 `grok2api` 命令，在 **Docker 环境** 中构建、启动、管理和排障 Grok2API 服务实例。

## 设计原则

- 宿主机只负责执行 `grok2api` 命令
- CLI 自身也运行在 Docker 容器中，不依赖宿主机 Python 环境
- Grok2API 服务实例始终运行在 Docker 容器中
- 实例数据、日志和本地覆盖配置都收口到仓库内 `.grok2api/`

## 前置要求

- 已安装 `docker`
- 已安装 `docker compose`
- 当前用户对 Docker socket 有访问权限

## 安装命令入口

首次使用时，在仓库根目录执行：

```bash
chmod +x ./grok2api
./grok2api install
```

安装完成后，如果安装目录在你的 `PATH` 中，就可以直接使用：

```bash
grok2api list
```

默认会安装到以下目录中的第一个可写目录：

- `$HOME/.local/bin`
- `$HOME/bin`
- `/usr/local/bin`

如果你要自定义安装目录：

```bash
GROK2API_BIN_DIR=/custom/bin ./grok2api install
```

卸载入口：

```bash
./grok2api uninstall
```

## 本地个性化配置

项目通用默认项定义在 [config.defaults.toml](/home/asimov/repos/grok2api/config.defaults.toml) 的 `cli.*` 配置节中。

你自己的本地覆盖配置请写到仓库内忽略文件 `.grok2api/cli.toml`：

```toml
[defaults]
proxy = "http://127.0.0.1:11111"
```

常见用途：

- 设置宿主机代理
- 覆盖默认端口
- 覆盖默认镜像名
- 覆盖默认 `flaresolverr` 行为

例如禁用默认开启的 `flaresolverr`：

```toml
[flaresolverr]
enabled = false
```

## 代理连通方式

CLI 管理实例时，代理优先级如下：

1. `grok2api start --proxy ...`
2. `.grok2api/cli.toml` 中的 `[defaults].proxy`
3. 宿主机环境变量 `GROK2API_HOST_PROXY`
4. 宿主机环境变量 `ALL_PROXY` / `HTTPS_PROXY` / `HTTP_PROXY`

`grok2api` 包装器会把这些代理环境变量透传给 CLI 容器，CLI 再把它们写入实例的 `config.toml`。

如果代理地址是 `http://127.0.0.1:11111` 或 `http://localhost:11111` 这种宿主机本地地址，会自动改写成：

```text
http://host.docker.internal:11111
```

这样 Docker 实例中的 Grok 请求就能真正连到宿主机代理。

注意：这一步并不等于容器可以访问宿主机 `127.0.0.1` 本身。

在 Linux 上，如果你的代理程序只监听：

```text
127.0.0.1:11111
```

那么即使 CLI 自动把地址改写成：

```text
http://host.docker.internal:11111
```

容器里依然可能连不上。原因是：

- `host.docker.internal` 指向的是宿主机网关地址，不是宿主机自己的 loopback
- 只绑定在 `127.0.0.1` 的服务，通常不会接受来自 Docker bridge 网关地址的连接

这时你需要让宿主机代理至少监听以下其中一种地址：

- `0.0.0.0:11111`
- 宿主机 Docker bridge 地址，例如 `172.17.0.1:11111`

如果你不确定当前监听地址，可以在宿主机执行：

```bash
ss -ltn '( sport = :11111 )'
```

如果结果是：

```text
127.0.0.1:11111
```

那就说明这类错误正是监听地址导致的，而不是 Grok2API 的 API 鉴权问题。

对于根目录的 `docker-compose.yml`，也支持以下方式：

```bash
export GROK2API_HOST_PROXY=http://127.0.0.1:11111
docker compose up -d --build
```

或者直接复用你已有的标准代理环境变量：

```bash
export ALL_PROXY=http://127.0.0.1:11111
docker compose up -d --build
```

服务启动时会在当前 `proxy.base_proxy_url` / `proxy.asset_proxy_url` 为空时，从这些环境变量自动引导配置。

## 常用命令

构建服务镜像：

```bash
grok2api build
```

启动默认实例：

```bash
grok2api start
```

启动指定实例：

```bash
grok2api start demo --port 34568 --proxy http://127.0.0.1:11111
```

显式控制 `flaresolverr`：

```bash
grok2api start demo --no-flaresolverr
grok2api start demo --flaresolverr --flaresolverr-url http://flaresolverr:8191
grok2api start demo --cf-refresh-interval 900 --cf-timeout 90
grok2api restart demo --no-flaresolverr
grok2api restart demo --flaresolverr-log-level debug
```

停止、重启、删除：

```bash
grok2api stop demo
grok2api restart demo
grok2api remove demo
```

列出实例：

```bash
grok2api list
```

查看状态和健康检查：

```bash
grok2api status
grok2api status demo
```

查看日志：

```bash
grok2api logs demo
grok2api logs demo --tail 300
grok2api logs demo -f
```

## 默认行为

- 默认实例名：`default`
- 默认宿主机端口：`34567`
- 默认容器端口：`8000`
- 默认代理：关闭
- 默认开启 `flaresolverr` sidecar
- 默认 `flaresolverr` 地址：`http://flaresolverr:8191`
- 默认 CF 刷新间隔：`600` 秒
- 默认 CF 超时：`60` 秒
- 如果配置了 `http://127.0.0.1:11111` 这类宿主机本地代理，CLI 或 Compose 启动流程都会自动改写成 `http://host.docker.internal:11111` 后写入容器配置
- 实例数据目录：`.grok2api/instances/<name>/data`
- 实例日志目录：`.grok2api/instances/<name>/logs`

默认情况下，CLI 新生成的实例 compose 会同时包含：

- `GROK2API_HOST_PROXY` / `GROK2API_HOST_ASSET_PROXY` 环境变量
- `FLARESOLVERR_URL` / `CF_REFRESH_INTERVAL` / `CF_TIMEOUT` 环境变量
- `flaresolverr` sidecar 服务

第一次启动或第一次重建后，`cf_refresh` 需要一点时间完成挑战并把 `cf_clearance` 写入实例配置。在这段时间内，`chat/completions` 仍可能短暂返回 `403` 或 `502`。等日志中出现“刷新完成”后再测即可。

## 构建缓存

`grok2api build` 会优先使用 `docker buildx` 和本地缓存目录：

- 服务镜像缓存：`.grok2api/build-cache/service`
- CLI 镜像缓存：`.grok2api/build-cache/cli`

在依赖层没有明显变化时，可以减少重复下载和重建。

如果当前环境没有 `docker buildx`，会自动回退到普通 `docker build`。

## CLI 运行时镜像

`grok2api` 包装器本身会先准备一个 CLI 专用镜像，由 [Dockerfile.cli](/home/asimov/repos/grok2api/Dockerfile.cli) 定义。

可选环境变量：

- `GROK2API_CLI_IMAGE`：自定义 CLI 镜像名
- `GROK2API_CLI_PYTHON_VERSION`：切换 CLI 容器使用的 Python 版本
- `GROK2API_CLI_REBUILD=1`：强制重建 CLI 镜像
- `GROK2API_BIN_DIR`：指定 `install` 命令的安装目录

示例：

```bash
GROK2API_CLI_REBUILD=1 grok2api list
GROK2API_CLI_PYTHON_VERSION=3.12 grok2api list
```

## 实际访问

实例启动后，可通过以下地址访问：

- 管理面板：`http://127.0.0.1:<port>/admin`
- 健康检查：`http://127.0.0.1:<port>/health`
- API：`http://127.0.0.1:<port>/v1/...`

## 已验证流程

以下流程已在当前环境实际验证通过：

```bash
./grok2api install
grok2api build
grok2api start cli-test --port 34569
curl http://127.0.0.1:34569/health
grok2api status cli-test
grok2api logs cli-test --tail 20
grok2api remove cli-test
```

另外，代理自动连通流程也应按下面方式验证：

```bash
export GROK2API_HOST_PROXY=http://127.0.0.1:11111
grok2api start cli-proxy-test --port 34570
grok2api status cli-proxy-test
grok2api remove cli-proxy-test
```

在当前环境中，还额外验证了以下流程：

```bash
grok2api start default --port 34567
python debugs/test_chat_completions.py
```

结果为：健康检查通过，`cf_refresh` 成功写入 `cf_clearance`，`chat/completions` 的非流式和流式都返回 `200`。