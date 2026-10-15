# nixos-orca

独立的 Orca 原生服务端 Nix 包，仅支持 `x86_64-linux`。初始固定版本为 **1.4.224**，来源是 [stablyai/orca 官方 release](https://github.com/stablyai/orca/releases/tag/v1.4.224) 的 `orca-ide_1.4.224_amd64.deb`；`source.json` 中的 `version`、SHA-256 SRI `hash` 是版本更新的唯一输入。

包提取 release 已有的 `orcad-template` 和 `linux-x64-glibc` 原生模块，使用锁定 nixpkgs 的 Node.js 24 直接运行服务端与 CLI；不启动 Electron、不重编译原生模块，也不依赖其他主机配置仓库。nixpkgs 初始锁定到 `eaad089433ca2bb662274377d33df3d0e51ef28b`。

## 本地使用与验证

需要支持 flakes 的 Nix 和 Python 3：

```sh
nix build .#orca-server --out-link result
python3 scripts/smoke.py --package result
./result/bin/orca-server-cli --help
```

**集成者获准验证后应执行前两条命令**；它们与 CI 的构建、smoke 命令一致。构建输出提供 `orca-server`、`orca-server-cli`，不覆盖现有的 `orca` 命令。

运行时用户数据沿用 Orca 自身基于 `HOME` 的默认行为，亦可按 Orca 支持的方式显式设置 `ORCA_USER_DATA` / `ORCA_USER_DATA_PATH`。wrapper 不固化某台主机的数据目录或 Git 配置。CA 兼容 NixOS 系统默认设置；调用者可通过证书环境变量覆盖。服务账户、数据目录权限、systemd、ACL、防火墙和 Git 身份均由消费者主机管理。

## 主机 flake 消费

将本仓库作为**独立且由主机 `flake.lock` 锁定**的输入，而非复制包实现：

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

这是合并进现有 flake 的片段，保留主机原有的 nixpkgs 和模块定义。**不要设置 `inputs.orca.inputs.nixpkgs.follows = "nixpkgs"`**：该包应使用本仓库锁定的 nixpkgs，以与 CI 的 derivation / Cachix 缓存路径一致。主机升级此输入后才会消费新版本；更新 PR、缓存上传均不会自动部署任何服务器。

## 启用 Cachix

公开缓存为 [`nixos-orca-server`](https://nixos-orca-server.cachix.org)，公钥已从 [Cachix 公共接口](https://app.cachix.org/api/v1/cache/nixos-orca-server) 核实。缓存创建不等于包已上传；仍需确认 CI build、smoke、publish 和准确输出的缓存覆盖。

1. 使用已创建的公开缓存 `nixos-orca-server`。
2. 在 GitHub 仓库 **Settings → Secrets and variables → Actions → Secrets** 配置 Repository secret **`CACHIX_AUTH_TOKEN`**：对此缓存具有写权限的 token，建议缓存专用的最小权限 token。不要提交 token，不要放进 Nix 文件、日志或公开 variable。缓存名已固定在 workflow 中，无需设置 `CACHIX_CACHE` variable。
3. 在消费者主机的 Nix 配置中启用以下缓存与公钥（GitHub 不需要另填公钥变量）。GitHub 发布凭据不会让主机自动信任缓存：

   ```nix
   nix.settings.extra-substituters = [ "https://nixos-orca-server.cachix.org" ];
   nix.settings.extra-trusted-public-keys = [
     "nixos-orca-server.cachix.org-1:quDSJdySzgztwEIYcNbEParCqqwypz9Xi05Do22uyAk="
   ];
   ```
4. 向 `main` 推送，或在 Actions 手动运行 **Build and publish Orca** 并选择 `main`。确认 build、smoke、publish 均成功后，才能称缓存已发布。

CI 仅在本仓库 `main` 的 `push` / `workflow_dispatch` 上将 `CACHIX_AUTH_TOKEN` 注入发布 step。PR 只构建与 smoke，不能取得上传 token，也不会上传。手动选择其他分支同样只构建、smoke。发布 step 使用 `nix run --inputs-from . nixpkgs#cachix -- push ...`，从本仓库锁定的 nixpkgs 获取 Cachix CLI，并沿用 Nix 默认可信 `cache.nixos.org`；没有安装自动上传 hook，也不使用会自动上传未测试输出的 action。

## 版本更新

更新脚本仅依赖 Python 标准库。无参数时查询 GitHub 的 latest stable release；`--version` 精确指定不带 `v` 的稳定版本。draft / prerelease、缺少或不匹配的 amd64 资产、网络/API 错误都会直接失败，不会回退到旧 release 或伪造 hash。

```sh
# 只检查，不写文件、不下载大型 deb。
python3 scripts/update.py --check

# 下载官方 deb，流式计算 SHA-256，原子更新 source.json。
python3 scripts/update.py

# 精确选择稳定版本；初始版本相同则不下载、不改文件。
python3 scripts/update.py --version 1.4.224
```

`--check` 退出码：`0` 为目标版本已锁定，`1` 为版本不同，`2` 为获取/解析错误。普通更新遇到同一版本会保持文件不动，也不会重新下载；这是版本更新器，不是对同名资产重新上传的监控器。不同版本会验证官方资产 URL、下载字节数和 Debian archive 标识，再写入真实内容 hash。可用环境变量 `GITHUB_TOKEN` 提高 GitHub API 限额；token 只用于 API 请求，不打印、不发送到 release CDN。

`.github/workflows/update.yml` 每周一检查，也可手动指定版本；只在本仓库 `main` 运行，使用 `GITHUB_TOKEN` 把 `source.json` 的变化提交到 `update/orca` 分支并创建/更新 PR，不直接改 `main`。需在仓库 Actions 设置中允许 **Read and write permissions** 及 **Allow GitHub Actions to create and approve pull requests**；工作流实际仅申请 `contents: write`、`pull-requests: write`。

GitHub 默认不会对 `GITHUB_TOKEN` 创建的 PR 再触发 `pull_request` CI。**合并机器人 PR 前，应手动运行 Build and publish Orca，选择 `update/orca` 分支，检查 build 与 smoke 均通过**；这次分支运行不会上传缓存。合并后 `main` CI 再次构建、smoke，成功才上传。更新流程不自动合并、重启服务或修改主机锁文件。

## Actions 固定版本来源

所有第三方 action 均固定发布版本对应的完整 commit SHA；可从官方仓库 tag API 核对：

| Action | 发布版本 | 固定 commit / 官方证据 |
| --- | --- | --- |
| actions/checkout | v7.0.1 | [`3d3c42e5aac5ba805825da76410c181273ba90b1`](https://api.github.com/repos/actions/checkout/git/ref/tags/v7.0.1) |
| cachix/install-nix-action | v31.11.2 | [`448cde739abec1eaf0646249e3d25bb8d9bc7702`](https://api.github.com/repos/cachix/install-nix-action/git/ref/tags/v31.11.2) |
| peter-evans/create-pull-request | v8.1.1 | [`5f6978faf089d4d20b00c7766989d076bb2fc7f1`](https://api.github.com/repos/peter-evans/create-pull-request/git/ref/tags/v8.1.1) |

本仓库保留原有 `LICENSE`；上游 Orca 发行物的许可与使用条件仍由上游决定。
