# whatsent

**看清你的 AI 编程 Agent 把什么数据发到了哪里。** 一条命令：让任意 Agent 在一个埋满假密钥的临时项目里干活，同时记录它的网络流量和留在本地的文件，最后生成一页报告，告诉你哪些东西离开了你的电脑。

```bash
pipx install git+https://github.com/sundaysebasidian-byte/whatsent
whatsent run -- claude
```

[English](README.md)

## 为什么做这个

编程 Agent 能读到整个项目。它发出去的大部分内容是你让它处理的代码，这是正常的。问题在于还顺带发了什么：`.env`、被 gitignore 的凭据、git 历史、你根本没提过的文件，甚至整个工作区的打包快照。厂商的隐私说明讲的是意图，whatsent 看的是实际行为。

whatsent 是审计工具，不是防火墙，不拦截任何东西。

## 原理

1. **金丝雀项目**：自动生成一个小型假项目，每个文件里埋一个唯一的随机标记：任务相关文件、无关源文件、被 gitignore 的 `.env`、被 gitignore 的凭据文件、一个"文件名本身就是标记"的文件、一条 git 提交信息。所有值都明显是假的，每次运行都重新生成。
2. **抓包**：在本地启动 [mitmproxy](https://mitmproxy.org)，给 Agent 设置 `HTTPS_PROXY` 和本次运行专用的 CA 证书，从而读取 HTTPS 请求。每个请求都会搜索标记，包括 gzip、URL 编码、base64、zip/tar 包里的内容。
3. **落盘监控**：运行前后各给 Agent 的缓存和配置目录拍一次快照。对上传内容加密的工具通常会先在本地生成打包文件，whatsent 会列出新出现的压缩包和大文件，并在里面搜索标记。
4. **绕过检测**：运行期间采样 Agent 打开的网络连接，绕开代理的连接会标为"未能检查"，而不是被当成干净。
5. **报告**：在 `./whatsent-report/<时间>/` 下生成单文件 `report.html`（附 `report.json`）：哪些标记被发出、发往哪些域名、上传了多少、落盘了什么、哪些流量没能检查。

## 用法

```bash
whatsent run -- claude                       # 交互式：输入提示的任务，完成后退出 Agent
whatsent run -- codex exec "Fix the bug in src/app.py so that add() returns the sum of its arguments."
whatsent run -- gemini
whatsent run -- aider --yes-always --message "Fix the bug in src/app.py so that add() returns the sum of its arguments."
```

Agent 启动前 whatsent 会打印一句建议的任务提示。对比多个 Agent 时请用同一句提示。Agent 在金丝雀项目里运行，使用你平时的登录和设置。

| 参数 | 含义 |
| --- | --- |
| `--out DIR` | 报告目录（默认 `./whatsent-report`） |
| `--watch DIR` | 额外监控某个目录（可重复） |
| `--no-default-watch` | 只监控 `--watch` 指定的目录 |
| `--port N` | 固定代理端口 |
| `--mitm-set KEY=VALUE` | 透传 mitmproxy 选项，例如 `mode=upstream:http://corp-proxy:8080` |

默认监控 `~/.claude`、`~/.codex`、`~/.gemini` 等 Agent 目录；Linux 上另加 `~/.cache`、`~/.config`、`~/.local/share` 和临时目录，macOS 上另加 `~/Library/Caches` 和 `~/Library/Application Support`。浏览器缓存等嘈杂目录会跳过。

## 怎么看报告

- **红色**：任务根本不需要的东西被发出去了（`.env`、凭据、git 历史）。
- **橙色**：普通项目文件被发出去了。把你让它改的文件发给模型是正常的；发了无关文件或目录列表，说明它上传的上下文有多宽。
- **未能检查**：拒绝 whatsent 证书的域名（证书锁定）或绕开代理的连接。这一栏不为空时，"没有泄露"不能说明问题。
- **写入磁盘**：本地留下的副本（比如对话日志）和新出现的压缩包。如果大上传前刚好冒出一个压缩包，值得细看。

## 环境要求

- macOS 或 Linux，Python 3.10 及以上（macOS 自带 Python 太旧，请用 Homebrew 的 Python 或 `uv tool install`）。
- 要测试的 Agent 已安装并登录。

## 已知局限

- 只能解密遵守 `HTTP(S)_PROXY` 的流量。不走代理、做了证书锁定或自带信任库的工具会列在"未能检查"里，不做内容分析。Cursor、Trae 等 Electron/IDE 类 Agent 大多属于这种情况，系统层抓包在计划中。
- 连接采样每 0.2 秒一次，极短的直连可能漏掉。UDP/QUIC 内容不会被解密。
- 加密上传只能看到目的地和大小，看不到内容。落盘监控只有在工具把数据暂存在被监控目录时才有用。
- 落盘监控会标出被监控目录里所有新出现的大文件，包括运行期间其他程序写的。运行时间尽量短，其他应用尽量别动。
- 能识别明文、gzip、deflate、URL 编码、base64、zip 和 tar 里的标记。其他编码（例如代理无法解码的压缩 protobuf）可能藏住标记。
- 目前用模拟 Agent 在 Linux 上做了端到端测试。真实 Agent 还没有用 v0.1 跑过，各 Agent 的结果核实后再公布。

## 开发

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest
```

`tests/mock_agent.py` 是一个模拟 Agent：通过 HTTP 和 HTTPS 外泄、使用证书锁定的连接、绕开代理直连、在缓存目录留下快照。端到端测试在 `whatsent run` 下运行它，对接本地假服务端，完全离线。

## 许可证

MIT
