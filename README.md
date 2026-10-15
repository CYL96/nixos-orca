# nixos-orca

用于 NixOS 和 Linux 无桌面环境的 [Orca](https://github.com/stablyai/orca) 服务端 Nix 包。

从 Orca 官方发行包中提取服务端及预编译原生模块，使用 Nix 提供的 Node.js 运行，无需启动 Electron 或安装桌面环境。适合在远程开发机、虚拟机和常驻服务器上运行 Orca runtime，供 Orca 客户端连接。

## 特性与范围

- **无桌面依赖**：只打包服务端运行所需的文件，不包含 Electron。
- **可复现打包**：通过 `source.json` 固定上游版本和 SHA-256，通过 `flake.lock` 固定 Nix 依赖。
- **二进制缓存**：提供 Cachix 缓存，减少本地打包开销。
- **独立集成**：不绑定主机配置、服务账户、数据目录或 Git 身份。
- **独立命令**：提供 `orca-server` 和 `orca-server-cli`，不占用 `orca` 命令名。

目前仅支持 `x86_64-linux`，复用上游 `linux-x64-glibc` 原生模块，不从源码编译 Orca。

## 快速开始

需要已启用 flakes 的 Nix。

```sh
nix build github:CYL96/nixos-orca#orca-server
./result/bin/orca-server --help
./result/bin/orca-server-cli --help
```

`orca-server` 是服务端入口，`orca-server-cli` 用于命令行操作。客户端连接方式参见 [Orca Remote Servers 文档](https://www.onorca.dev/docs/remote-servers)；这两个命令是本项目提供的入口名，与上游 `orca` 命令的调用形式不同，具体参数以各自的 `--help` 为准。

### 使用二进制缓存

在 NixOS 配置中添加：

```nix
nix.settings.extra-substituters = [
  "https://nixos-orca-server.cachix.org"
];
nix.settings.extra-trusted-public-keys = [
  "nixos-orca-server.cachix.org-1:quDSJdySzgztwEIYcNbEParCqqwypz9Xi05Do22uyAk="
];
```

非 NixOS 环境可将对应的 `extra-substituters` 和 `extra-trusted-public-keys` 设置写入 Nix 配置。缓存地址：[nixos-orca-server.cachix.org](https://nixos-orca-server.cachix.org)。

## 集成到 NixOS flake

在现有 flake 中添加输入，并将包加入目标主机的模块：

```nix
{
  inputs.orca.url = "github:CYL96/nixos-orca";

  # 合并到现有 outputs，保留主机原有的 nixpkgs 和模块。
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

保留本项目独立的 nixpkgs 输入，不要设置 `inputs.orca.inputs.nixpkgs.follows = "nixpkgs"`，以保持包派生与 CI 发布的缓存一致。消费者通过自己的 `flake.lock` 锁定本项目；仓库发布新包不会自动升级或部署主机。

也提供 `overlays.default`。使用 overlay 会按消费者的 nixpkgs 重新生成派生，可能无法复用本项目发布的缓存。

### 运行与持久化

本项目提供软件包，不提供 NixOS 服务模块。部署时由主机配置管理：

- **服务账户与状态目录**：运行时默认使用 Orca 基于 `HOME` 的数据目录行为，也可显式设置 `ORCA_USER_DATA` / `ORCA_USER_DATA_PATH`；持久化该目录并限制访问权限。
- **进程管理**：通过 systemd 或其他进程管理器启动 `orca-server`，配置所需环境、启动参数和重启策略。
- **项目权限**：只授权需要访问的项目目录，不共享管理员凭据和整个 home。
- **网络与配对**：配置客户端可达的地址及必要的防火墙规则，将配对链接视为凭据。
- **Agent 工具**：在服务账户可用的环境中安装并认证需要运行的 Agent CLI。

包装器不固化 Git 配置；证书默认使用系统 CA，可通过 `SSL_CERT_FILE`、`NIX_SSL_CERT_FILE` 和 `NODE_EXTRA_CA_CERTS` 覆盖。

## 开发与维护

### 本地验证

在仓库根目录执行，需要 Python 3：

```sh
nix build .#orca-server --out-link result
python3 scripts/smoke.py --package result
```

Smoke 脚本在临时环境中检查服务启动、加密配对 RPC、Git 项目与 worktree、PTY 及服务重启后的连接行为。

当前锁定版本为 **Orca 1.4.226**，已通过上述构建与 smoke 验证。

### 跟进上游版本

`source.json` 保存上游版本和发行包 hash。更新脚本仅依赖 Python 标准库：

```sh
# 检查最新稳定版，不修改文件、不下载发行包。
python3 scripts/update.py --check

# 下载最新稳定版发行包、计算 SHA-256 并更新 source.json。
python3 scripts/update.py
```

可通过 `--version` 指定不带 `v` 前缀的稳定版本。`--check` 退出码：`0` 表示目标版本已锁定，`1` 表示版本不同，`2` 表示查询或解析失败。

GitHub Actions 的 **Propose Orca release update** 每天北京时间 07:00（前一天 UTC 23:00）检查上游，也支持手动指定版本，并创建或更新 `update/orca` PR，不直接修改 `main`。机器人使用 `GITHUB_TOKEN` 创建的 PR 不会自动触发 PR CI；合并前需手动运行 **Build and publish Orca**，选择 `update/orca` 分支检查构建与 smoke。

**Build and publish Orca** 在 PR 上执行构建与 smoke，仅在本仓库 `main` 的推送或手动运行中上传验证后的输出到 Cachix。维护者需配置缓存写入 Secret `CACHIX_AUTH_TOKEN`；更新 PR 还需允许 Actions 写入仓库及创建 PR。工作流不自动合并、修改消费者锁文件或部署服务。

## 许可证

Nix 打包代码见 [LICENSE](LICENSE)，Orca 上游许可证见 [LICENSE.upstream](LICENSE.upstream)。打包产物同时包含相关许可证文件。
