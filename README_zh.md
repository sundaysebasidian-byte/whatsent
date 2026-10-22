# whatsent

**看清你的 AI 编程 Agent 把什么数据发到了哪里。** 一条命令：让任意 Agent（命令行或 IDE）在一个埋满假密钥的临时项目里干活，同时记录它的网络流量和留在本地的文件，最后生成一页报告，告诉你哪些东西离开了你的电脑。

![whatsent 报告：6 个金丝雀里有 3 个离开了本机，其中包括 .env 密钥](docs/report.png)

<sub>上图来自 `whatsent demo`：一个模拟 Agent 对接本地假服务端，不是任何真实产品。</sub>

```bash
pipx install git+https://github.com/sundaysebasidian-byte/whatsent   # 或：uv tool install git+https://...
whatsent demo                  # 10 秒离线演示，不需要装 Agent
whatsent run -- claude         # 命令行 Agent
whatsent run --app cursor      # IDE 类 Agent
```

[English](README.md) · [测评榜](https://sundaysebasidian-byte.github.io/whatsent/) · [示例报告](https://sundaysebasidian-byte.github.io/whatsent/sample-report.html)

## 为什么做这个

编程 Agent 能读到整个项目。它发出去的大部分内容是你让它处理的代码，这是正常的。问题在于还顺带发了什么：`.env`、被 gitignore 的凭据、git 历史、你根本没提过的文件，甚至整个工作区的打包快照。厂商的隐私说明讲的是意图，whatsent 看的是实际行为。

whatsent 是审计工具，不是防火墙，不拦截任何东西。

## 原理

1. **金丝雀项目**：自动生成一个小型假项目，每个文件里埋一个唯一的随机标记：任务相关文件、无关源文件、被 gitignore 的 `.env`、被 gitignore 的凭据文件、一个"文件名本身就是标记"的文件、一条 git 提交信息。所有值都明显是假的，每次运行都重新生成。
2. **抓包**：在本地启动 [mitmproxy](https://mitmproxy.org)，让 Agent 走这个代理并信任本次运行专用的 CA 证书，从而读取 HTTPS 请求。每个请求都会搜索标记，包括 gzip、zstd、URL 编码、base64、zip/tar，以及 gRPC/Connect 里压缩过的消息。
3. **落盘监控**：运行前后各给 Agent 的缓存和配置目录拍一次快照。对上传内容加密的工具通常会先在本地生成打包文件，whatsent 会列出新出现的压缩包和大文件，并在里面搜索标记。
4. **绕过检测**：运行期间采样 Agent 打开的网络连接，绕开代理的连接（TCP 或 UDP/QUIC）会标为"未能检查"，而不是被当成干净。
5. **报告**：在 `./whatsent-report/<时间>/` 下生成单文件 `report.html`，附 `report.json` 和可公开分享的 `result.json`。报告里你的用户目录显示为 `~`。

## 用法

### 命令行 Agent

```bash
whatsent run -- claude                       # 交互式：输入提示的任务，完成后退出 Agent
whatsent run -- codex exec "Fix the bug in src/app.py so that add() returns the sum of its arguments."
whatsent run -- gemini
whatsent run -- aider --yes-always --message "Fix the bug in src/app.py so that add() returns the sum of its arguments."
```

Agent 启动前 whatsent 会打印一句建议的任务提示。对比多个 Agent 时请用同一句提示。Agent 在金丝雀项目里运行，使用你平时的登录和设置。

### IDE 类 Agent（Cursor、Trae、Windsurf 等）

```bash
whatsent run --app cursor                    # 还支持：trae、trae-cn、windsurf、kiro、qoder、codebuddy、vscode
whatsent run --app "/Applications/Some IDE.app"
```

先把这个 App 完全退出：再次启动会被交给已经在运行的那个实例，whatsent 就看不到了。whatsent 会直接启动 App 自己的程序，打开金丝雀项目，并加上 Chromium 的 `--proxy-server`、`--ignore-certificate-errors`、`--disable-quic` 参数。忽略证书错误只在这次运行生效，而且 App 只会收到 whatsent 本地代理出示的证书；mitmproxy 自己仍会校验真实服务器的证书。在 AI 对话里输入建议的任务，等它做完，再退出 App（Cmd+Q）。

### 不走代理的流量（实验性）

```bash
whatsent run --capture local -- some-agent
whatsent run --app trae --capture local:Trae
```

`--capture local` 会加上 mitmproxy 的本地抓包模式（local mode），在系统层把匹配进程的流量导到代理。macOS 第一次会请你允许 mitmproxy 的系统扩展；Linux 需要 root。用这种方式抓到的域名会在报告里标为 "ignored proxy, caught at OS level"（无视代理设置、在系统层抓到）。如果系统层抓包没能启动，报告会明确提示，而不是显示成干净。

### 参数

| 参数 | 含义 |
| --- | --- |
| `--app 名称\|路径` | 启动桌面 IDE 类 Agent |
| `--capture env\|local[:SPEC]` | 只用代理设置（默认），或对匹配 SPEC 的进程加上系统层抓包 |
| `--name`、`--agent-version` | 在报告和测评榜里标注 Agent 名称和版本 |
| `--out DIR` | 报告目录（默认 `./whatsent-report`） |
| `--watch DIR` | 额外监控某个目录（可重复） |
| `--no-default-watch` | 只监控 `--watch` 指定的目录 |
| `--port N` | 固定代理端口 |
| `--mitm-set KEY=VALUE` | 透传 mitmproxy 选项，例如 `mode=upstream:http://corp-proxy:8080` |

默认监控 `~/.claude`、`~/.codex`、`~/.gemini`、`~/.cursor`、`~/.trae` 等 Agent 目录；Linux 上另加 `~/.cache`、`~/.config`、`~/.local/share` 和临时目录，macOS 上另加 `~/Library/Caches` 和 `~/Library/Application Support`。浏览器缓存等嘈杂目录会跳过。

## 怎么看报告

- **红色**：任务根本不需要的东西被发出去了（`.env`、凭据、git 历史）。
- **橙色 / →**：普通项目文件被发出去了。把你让它改的文件发给模型是正常的；发了无关文件或目录列表，说明它上传的上下文有多宽。
- **未能检查**：拒绝 whatsent 证书的域名（证书锁定）或绕开代理的连接。这一栏不为空时，"没有泄露"不能说明问题。
- **写入磁盘**：本地留下的副本（比如对话日志）和新出现的压缩包。如果大上传前刚好冒出一个压缩包，值得细看。

## 测评榜

`whatsent board results/ -o site/` 会把多份 `result.json` 汇总成一个静态页面和 `leaderboard.json`，由 GitHub Actions 发布到 GitHub Pages。想加一个 Agent：用建议的任务跑一遍，然后提 PR 把它的 `result.json` 放进 [`results/`](results/README.md)。`result.json` 只有汇总数据：哪些金丝雀被发出、目的域名、字节数，不含路径、提示词或文件内容。

在有真实结果之前，测评榜展示的是虚构 Agent 的示例数据，页面上会明确标注为示例（见 [examples/make_examples.py](examples/make_examples.py)）。

## 环境要求

- macOS 或 Linux，Python 3.10 及以上（macOS 自带 Python 太旧，请用 Homebrew 的 Python、`pipx` 或 `uv tool install`）。
- 要测试的 Agent 已安装并登录。

## 已知局限

- 不加 `--capture local` 时，只能解密遵守代理设置的流量。做了证书锁定或自带信任库的工具会列在"未能检查"里，不做内容分析。
- IDE 支持依赖 Electron 遵守 `--proxy-server`、扩展进程遵守 `HTTPS_PROXY` / `NODE_EXTRA_CA_CERTS`。目前只用替身程序测过，还没用真实的 Cursor 或 Trae 测过。除了你直接传路径，内置的 App 名称不一定和你的安装一致。
- `--capture local` 还没在真实 Mac 上测过；Linux 下需要 root 和 eBPF。
- 连接采样每 0.2 秒一次，极短的直连可能漏掉。
- 加密上传只能看到目的地和大小，看不到内容。落盘监控只有在工具把数据暂存在被监控目录时才有用。
- 落盘监控会标出被监控目录里所有新出现的大文件，包括运行期间其他程序写的。运行时间尽量短，其他应用尽量别动。
- 真实 Agent 还没有用 whatsent 跑过，各 Agent 的结果核实后再公布。

## 开发

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest
```

`whatsent/demo_agent.py` 是一个模拟 Agent：通过 HTTP 和 HTTPS 外泄、使用证书锁定的连接、绕开代理直连、在缓存目录留下快照。`whatsent demo` 和端到端测试都在本地假服务端上运行它，完全离线。`tests/fake_app.py` 是 Electron IDE 的替身。

## 许可证

MIT
