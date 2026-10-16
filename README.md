# nixos-orca

将 [Orca](https://github.com/stablyai/orca) 官方预编译发行包中的 headless 服务端和 CLI 打包为 Nix 包，供 Orca 客户端连接。适用于 NixOS 和其他使用 Nix 的 Linux 主机，无需 Electron 或桌面环境。

## 范围与约束

- **仅支持 `x86_64-linux`**：使用官方 amd64 `.deb` 中的共享服务端文件及 `linux-x64-glibc` 原生模块，不编译 Orca 应用源码。
- **使用 Nix 提供的 Node.js 24**：预编译 addon 要求该主版本，不依赖主机安装的 Node.js 或 Bun。
- **保持上游载荷完整**：除 ELF 链接修复外，不改写上游 JS 和原生模块；不打包 Electron、其他架构或可能触发上游 Node 下载的运行时选择标记。
- **固定输入**：`source.json` 是上游版本和 SHA-256 SRI 的唯一来源，`flake.lock` 锁定 Nix 依赖。
- **只提供软件包**：不提供 NixOS 服务模块，不配置服务账户、状态目录、Git 身份、Agent 工具或主机部署。

Flake 导出 `packages.x86_64-linux.orca-server`、指向同一包的 `packages.x86_64-linux.default`，以及 `overlays.default`。

## 快速开始

需要 `x86_64-linux` 主机和已启用 flakes 的 Nix：

```sh
nix build github:CYL96/nixos-orca#orca-server --out-link result
./result/bin/orca-server-cli --version
./result/bin/orca-server --bind 127.0.0.1 --port 4010
```

最后一条命令在前台启动仅监听回环地址的服务。远程访问需使用 SSH 端口转发，或按部署需求显式配置监听地址、配对地址及防火墙；客户端连接参见 [Orca Remote Servers 文档](https://www.onorca.dev/docs/remote-servers)。

本包的入口名与上游 `orca` 不同，不占用 `orca` 命令名：

| 命令 | 用途 |
| --- | --- |
| `orca-server` | 启动 headless runtime |
| `orca-server-cli` | 通过 CLI 操作 runtime；多数操作需要已运行的服务 |

具体参数分别以 `orca-server --help` 和 `orca-server-cli --help` 为准。CLI 帮助中的 `orca` 示例应改用 `orca-server-cli`；本包不提供 Electron 桌面应用。

### 可选：使用二进制缓存

在 NixOS 配置中添加：

```nix
nix.settings.extra-substituters = [
  "https://nixos-orca-server.cachix.org"
];
nix.settings.extra-trusted-public-keys = [
  "nixos-orca-server.cachix.org-1:quDSJdySzgztwEIYcNbEParCqqwypz9Xi05Do22uyAk="
];
```

非 NixOS 环境可在 Nix 配置中设置对应的 `extra-substituters` 和 `extra-trusted-public-keys`。缓存仅用于复用已发布的构建产物；未命中时仍需构建。

本仓库 CI 仅在受信任的 `main` 推送或 `main` 手动运行中，将通过构建和 smoke 验证的产物上传 Cachix。

## 集成到 NixOS flake

将以下片段合并到现有 flake，保留主机原有的 `nixpkgs` 输入和模块：

```nix
{
  inputs.orca.url = "github:CYL96/nixos-orca";

  outputs = { self, nixpkgs, orca, ... }: {
    nixosConfigurations.my-host = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        ({ ... }: {
          environment.systemPackages = [
            orca.packages.x86_64-linux.orca-server
          ];
        })
      ];
    };
  };
}
```

为保持与 CI 缓存的派生一致，保留本项目独立的 nixpkgs 输入，不要设置 `inputs.orca.inputs.nixpkgs.follows = "nixpkgs"`。使用 `overlays.default` 会改用消费者的 nixpkgs，可能失去缓存复用；平台和 Node.js 24 的断言仍然适用。

消费者通过自己的 `flake.lock` 锁定本项目。仓库发布新包不会自动更新消费者锁文件或部署主机。

## 运行与部署责任

主机配置负责以下事项，本包不会替代部署管理：

- **账户与持久化**：使用专用服务账户，明确其 `HOME` 和持久状态目录；可通过 `ORCA_USER_DATA` / `ORCA_USER_DATA_PATH` 显式指定 Orca 数据目录，并限制访问权限。
- **进程管理**：使用 systemd 或其他进程管理器配置启动参数、环境、日志和重启策略。
- **项目与凭据**：只授权需要访问的项目目录，自行配置 Git 身份和认证，不共享管理员凭据或整个 home。
- **网络与配对**：按访问方式配置监听地址、配对地址及防火墙。配对链接相当于访问凭据，不要公开、提交到仓库或写入公共日志。
- **Agent 工具**：在服务账户可用的环境中安装并认证所需的 Agent CLI。

包装器提供 Node.js 24，将 Git、Bash 和 coreutils 加入 `PATH`，并在未设置 `SHELL` 时默认使用 Bash。它不固化 Git 配置，也不安装 Agent CLI。

CA 默认优先使用可读的系统证书包，否则使用 Nix 的 `cacert`。调用方设置的 `SSL_CERT_FILE`、`NIX_SSL_CERT_FILE` 和 `NODE_EXTRA_CA_CERTS` 会被保留。

配对信息从服务启动输出获取，日志位置由主机部署决定，本包不创建固定的 `startup.log`。仅由服务账户或有权限的管理员读取，不要为提取链接而放宽日志权限。

### 随时查看配对链接

要在忘记链接后用一条命令找回，可将服务启动输出追加到受保护的持久日志。下面是**现有 NixOS 服务的配置片段**，放入上文可访问 `orca` flake 输入的主机模块中：

```nix
systemd.services.orca-server = {
  script = ''
    exec >> /var/lib/orca/startup.log 2>&1
    exec ${orca.packages.x86_64-linux.orca-server}/bin/orca-server \
      --bind 127.0.0.1 --port 4010 \
      --pairing-address 127.0.0.1 --json
  '';
  serviceConfig = {
    StateDirectory = "orca";
    StateDirectoryMode = "0700";
    UMask = "0077";
    StandardOutput = "null";
    StandardError = "journal";
  };
};
```

保留现有服务的 `User`、`Group`、`HOME`、Orca 数据目录和进程管理配置；这不是完整的服务模块。用上面的 `script` 替换原启动定义，若原来显式设置了 `serviceConfig.ExecStart`，需移除该定义，避免与 `script` 冲突。已有日志应由服务账户持有，权限为 `0600`；`UMask` 只约束新建文件，不会修复旧文件权限。

示例采用回环地址，远程客户端需通过 SSH 将本机 `4010` 转发到服务器的 `127.0.0.1:4010`。如果现有部署使用局域网直连，请保留实际的监听地址、端口及客户端可达的 `--pairing-address`。不要添加 `--no-pairing`。

应用 NixOS 配置并让服务按新配置启动后，以服务账户执行以下命令，即可随时输出**最后一次记录的完整配对链接**：

```sh
grep -oE 'orca://pair\?code=[A-Za-z0-9_-]+' /var/lib/orca/startup.log | tail -n 1
```

无需 `jq` 或重启服务；已有部署若已按此路径保存启动输出，可直接执行。其他账户无读取权限时，由管理员读取日志，不要放宽目录或文件权限。

该命令读取的是历史记录，不代表服务当前在线；可用 `systemctl status orca-server.service` 查看运行状态。没有输出时，检查服务是否成功启动、是否启用配对，以及日志路径是否一致。这里的启动输出已重定向到文件，`journalctl -u orca-server.service` 不会显示配对链接。日志会持续追加，长期部署需自行配置保留最近启动记录的轮转策略；配对链接和日志都应按凭据保护。

## 开发与维护

### 构建与验收

在仓库根目录执行。除 Nix 外，还需要 Python 3、`PATH` 中可用的 Git，以及 Linux `/proc`：

```sh
nix build .#orca-server --out-link result
python3 scripts/smoke.py --package result
```

Smoke 验证该次构建的实际安装产物，在临时 HOME/XDG 和独立状态目录中检查：

- CLI 版本与 `source.json` 一致，运行中的 Node 主版本为 24。
- 服务启动及加密配对 RPC 可用。
- 真实 Git 仓库注册、worktree 创建及 PTY 命令执行。
- 重启后原配对链接仍可连接，仓库与 worktree 状态持久化。
- 服务正常关闭，并清理测试使用的私有 daemon。

发布 pin 或打包逻辑变更后，应一起执行构建和 smoke。Flake 没有 `checks` 输出，不要用 `nix flake check` 替代验收；仓库也未配置开发 shell、lint 或格式化命令。

### 更新上游版本

`scripts/update.py` 仅依赖 Python 标准库，解析官方稳定版元数据、下载 amd64 `.deb`、计算实际文件的 SHA-256 SRI，并原子更新 `source.json`。该文件必须且只能包含 `version` 和 `hash`，不要手填猜测的 hash。

```sh
# 只检查最新稳定版元数据，不下载发行包、不修改文件。
python3 scripts/update.py --check

# 更新到最新稳定版；若已锁定该版本则不下载、不改写。
python3 scripts/update.py
```

指定版本时添加 `--version <版本号>`，版本号不带 `v` 前缀。`--check` 退出码：`0` 表示目标版本已锁定，`1` 表示存在版本差异，`2` 表示处理过的查询、解析等失败。更新脚本本身的变更需显式验证受影响行为，不能依赖构建 CI。

[Propose Orca release update](.github/workflows/update.yml) 工作流会定期检查更新，也支持手动指定版本，仅创建或更新 `update/orca` 分支上修改 `source.json` 的 PR，不自动合并。

**自动更新 PR 合并前必须手动验收**：`GITHUB_TOKEN` 创建的 PR 不会自动触发 PR CI。手动运行 [Build and publish Orca](.github/workflows/ci.yml)，选择 `update/orca` 分支，确认构建和 smoke 通过；该分支不会上传缓存。

## 许可证

Nix 打包代码见 [LICENSE](LICENSE)，Orca 上游许可证见 [LICENSE.upstream](LICENSE.upstream)。安装产物在 `$out/share/licenses/orca-server/` 中包含打包、Orca、node-pty 和 Parcel watcher 的许可证。
