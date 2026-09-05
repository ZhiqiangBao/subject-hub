# 学科 Hub · 远景规划

本文只记**以后可以做、现在不要做**的扩展。近期任务仍写在 [下一阶段计划](plan.md)。不要为这些条目改当前 Ubuntu 装机路径。

原则不变：学生始终打开一台主机的 `8090`（现在是浏览器，以后可以是同一套网页的 WebView 壳）；不要每学生一份判题程序、不要在学生页填密钥、不要把手机当评测主机。

## 启动与分发（可能的方向，现在不做）

正式装机仍是 Ubuntu + systemd。Windows 代码签名现在和可见的未来都搞不定，**不要做要签名的 exe / 安装向导 / 商店包**。

下面只是讨论过的可能方向，不是已定方案，不要为此改 `setup-ubuntu.sh`、不要改学生端。对照物是 **Nous Hermes Agent**。本机 GUI 源码在 `D:\hermes\hermes-agent\apps\desktop`：开发用 `npm run dev`（Vite + `electron .`），日常用 `hermes desktop`（在仓库里打一份 `release/win-unpacked` 再启动）。真正要签名的 NSIS/Tauri 安装包是另一条可选线，你这套日常可以感觉不到。学科 Hub 要对齐的是「命令/脚本拉起本机后端 + 界面」；不要去再发一个要签名的安装 exe。

### 学 Hermes Agent：本机后端 + 浏览器当 GUI

Hermes 真正不靠你办 Windows 签名的日常用法，和 `apps/desktop` 对得上：

1. PowerShell / `install.ps1` 在用户目录备好 Python 运行时（uv）。
2. 长期跑本机后端 `hermes serve`。
3. GUI 在 `apps/desktop`：React + **Electron 当窗口**，连后端的 WebSocket，不是系统浏览器；启动方式是 **`npm run dev` 或 `hermes desktop`**，不是去双击一个你分发的安装包。
4. 文件夹里 `npm run dist:win` / 旁边的 `apps/bootstrap-installer`（Tauri，注释写 *signed installer*）才会做出要签名的安装程序。本机 `D:\hermes\desktop` 是空的，说明日常没用安装包那条。
5. `release/win-unpacked/Hermes.exe` 是 electron-builder 打的 **未打包 Chromium 运行时**（约两百兆），由 `hermes desktop` 在本仓库里生成并拉起，不是商店里下的那个安装器。

映射到学科 Hub（若以后做 Windows 主机）：

| Hermes Agent | 学科 Hub |
| --- | --- |
| `install.ps1` / 一键脚本 | 下载已构建包、校验、写入用户目录 |
| `hermes serve` | uvicorn：8090 局域网答题，8091 仅本机注册管理员 |
| 浏览器打开 dashboard | 系统浏览器打开 `http://127.0.0.1:8091`，学生用 `http://<局域网IP>:8090` |
| `%LOCALAPPDATA%\hermes` 数据目录 | 可写 `data/`（账号、成绩、本地题），不写进只读安装位置 |
| 可选 Electron 桌面壳 | **不做**（要签名、也不是老师刚需） |

「可执行」就是启动脚本：拉起后台、等到端口通、再打开浏览器。要能停掉进程。运行时网页应已打好，不要在老师机器上 `npm run build`。

Qwen Code 的 `irm … | iex` 是同一类入口（脚本 + 压缩包 + SHA256，不是 Authenticode）。校验和只证明没下错。学校禁脚本、杀毒误报、用户不敢贴命令，仍可能挡住。老师家长日常仍只开浏览器；脚本只给**那台当主机的电脑**。

Hermes **没有破解 Windows 签名校验**。它换了一条本来就不要求 Authenticode 的通道：下的是脚本，在用户目录用 uv 装 Python、clone 源码；`venv\Scripts\hermes.exe` / `bin\hermes.exe` 是安装时生成的命令垫片（约 45KB，未签名），不是分发安装包。可选的 `Hermes-Setup.exe`（Tauri）才要签，日常可以不用。Linux 没有 Authenticode，Ubuntu 上 `setup-ubuntu.sh` 已经是等价做法，不必再学一遍「躲签名」。

### 不要把产品定义成「和 qwen-code 一样靠 npm 跑」

qwen-code 能 `npm i -g` 再敲命令，是因为它本身是 Node 程序。学科 Hub 的判题、题库、SQLite、模型队列在 Python / FastAPI。npm 不会自动变成这个后端的运行时。

| 做法 | 备注 |
| --- | --- |
| 启动脚本：后台服务 + 打开浏览器 | 可行，也简单，不需要签名 |
| `npm i -g` 只当安装/启动器，再调本机 Python | 能做，但主机要同时有 Node 和 Python |
| 后端整站改写成 Node，真的只靠 npm | 等于重写，不是换启动方式 |

老师家长那台机往往没有 Node。不要把最终产品写成必须先装 npm。

## 运行环境

| 角色 | 远景 | 现在不要当成正式方案 |
| --- | --- | --- |
| Ubuntu 主机 | 继续作为家庭/学校常开评测机 | — |
| Windows 本机当主机 | 源码已能跑；以后若做，优先脚本一键（见上），不做签名包 | 现在不要做安装器 |
| WSL | 开发、试用可以 | 不要当家里常开主机（端口、休眠） |
| 手机 / 平板 | **只当客户端**连 8090（浏览器，以后可套 WebView 壳） | 不要当服务端（休眠、IP、后台限制） |

### 手机客户端：封装网页，不当主机

学生/老师用手机只打开登录和答题页。判题、SQLite、密钥仍在 Ubuntu。壳子是系统 WebView（Chromium / WKWebView），界面上没有浏览器地址栏；不是再写一套原生答题。

**现在**：系统浏览器打开 `http://<主机IP>:8090`。  
**以后若要「不像浏览器」**：

1. 先做 PWA「添加到主屏幕」。不用办证书、不上架、不签 APK。iPhone 没有开发者账号时也只能走这条。
2. 安卓真要独立图标：Capacitor / Cordova / TWA 套同一套网页。家里/班级侧载 APK 用自签 keystore 即可（安卓签名，不是 Windows Authenticode）。Google Play / App Store 现在不要做。
3. 学校禁「未知来源」时侧载会失败，仍用浏览器或 PWA。

局域网是 HTTP。安卓壳要允许明文；iOS WebView 对 HTTP 更严，所以 iPhone 更适合 PWA。壳子按同源调 API，不能写死 `localhost`，必须指向这台主机的 8090。8091 不要写进学生端。

### 不填 IP：发现主机，不是另开端口

App **不能**凭「8090」这个端口号直接连上某台机器。底下永远是 TCP：先有地址，再连 `地址:8090`。不填 IP，只是让机器替人找地址。

| 做法 | 学生要做什么 | 说明 |
| --- | --- | --- |
| `subject-hub.local`（mDNS / Avahi） | 几乎不用填 | 浏览器就能用，不必先做 App。学校网常禁组播。多台主机时仍要选。 |
| App 扫网段上的 8090 | 不用填，多台时选一下 | 慢、费电，有的网禁扫描。 |
| 主机出示二维码 | 扫一次 | 组播被禁时最稳。 |
| 路由固定 DHCP / 内部域名 | 用名字打开 | 改路由，不是 App 能力。 |

现在若只是不想填数字，优先 Ubuntu 开 Avahi，走 `http://subject-hub.local:8090`。组播不行再加二维码。不要为发现去改学生端答题逻辑。

### 主机提供 App 下载、绑死这台 IP

「从这台主机下的包，以后原生连这台」**对安卓侧载可以**；iOS 不行（Ubuntu 现签不出能装的 IPA）。

安装程序**不会**把「下载 URL」传给已装 App，所以要显式写入或从网页再递一次：

| 做法 | 利 | 弊 |
| --- | --- | --- |
| 下载时现打 APK，写入当前局域网 IP 或 `.local` 名 | 最贴近「下谁连谁」 | DHCP 换 IP 旧包作废；主机要会改包、对齐、自签；Chrome 下 APK 会警告 |
| 一份通用 APK + 下载页用 Intent 把 `window.location.origin` 塞进 App | 不按 IP 现打；换地址后用浏览器再点一次「打开」即可 | 第一次仍要先打开这台主机的网页才能下到包 |

两种都是 WebView 开现有登录页。完全零次接触做不到：总要先碰到这台主机（IP、`.local` 或二维码）才能下「属于它」的包。

若以后做：优先通用 APK + 下载页 Intent；现打带 IP 的包能做，但更脆。现在不要做。

## 明确仍后置

- 商店上架、自动更新通道、Windows Authenticode / 苹果开发者签。
- Docker / 公网 SaaS / 每学生独立端口。
- 手机当评测主机；把判题搬进手机 App。
- 多模型对比、听力口语（见 [大模型评分](llm-grading.md)）。
