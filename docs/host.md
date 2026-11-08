# 评测主机：安装与更新

给家里装机的人看。学生和家长只用浏览器打开网页。

服务名 `subject-hub`。答题端口 **8090**（局域网打开）。家长后台端口 **8091**，只绑在本机 `127.0.0.1`，用来注册管理员；可以注册多位家长。

## 第一次安装

依赖：Ubuntu、Python 3.10 或更新版本，以及受支持的 Node.js：22.22.2+（22 系列）、24.15+（24 系列）或 26+。安装脚本会检查版本；若系统仓库提供的 Node.js 不符合要求，请先安装受支持版本。

```bash
git clone https://github.com/ZhiqiangBao/subject-hub.git
cd subject-hub
chmod +x scripts/setup-ubuntu.sh scripts/run-ubuntu.sh scripts/update-from-github.sh scripts/rollback-ubuntu.sh
./scripts/setup-ubuntu.sh
```

脚本会建虚拟环境、装依赖、构建网页，并安装 systemd 服务：答题站 `0.0.0.0:8090`，家长后台 `127.0.0.1:8091`。

查局域网 IP：`hostname -I`。若开了 ufw：

```bash
sudo ufw allow 8090/tcp
```

浏览器打开：

```text
http://<IP>:8090          # 学生注册、答题；家长也在这里登录看进度
http://127.0.0.1:8091     # 仅本机：注册家长（管理员），可注册多位
```

8091 不要对局域网开放。多位家长各自用不同名字在 8091 注册后，用同一套 8090 登录即可。

## 网络与密钥安全

8090 使用未加密 HTTP，适用于你信任的家庭或学校局域网；不要把端口映射到公网，也不要在不可信的公共 Wi-Fi 上使用。8091 只用于在主机本机注册管理员，不能对局域网开放。管理员注册后仍在 8090 登录管理；管理接口需要管理员会话。

旧版 8090 可能允许未登录访问者读取文件。若旧版 8090 曾被不受信任的设备访问，可按需轮换会话签名密钥；这是预防性操作，不表示已经发生泄露。先按[数据在哪](#数据在哪)停止服务、备份并验证实际数据目录，确认成功后保持服务停止。若服务环境中设置了 `SUBJECT_HUB_SECRET`，应在其配置来源替换该值（环境变量优先于文件）。否则，以服务账号在默认仓库内 `data/`（或实际数据目录）生成新的 `secret.txt`：

```bash
sudo systemctl stop subject-hub
systemctl is-active subject-hub   # 确认输出 inactive；并确认没有其它进程写数据目录
SERVICE_USER="$(systemctl show --value --property=User subject-hub.service)"
sudo -u "$SERVICE_USER" sh -c 'umask 077; python3 -c "import secrets; print(secrets.token_hex(32))" > /绝对数据目录/secret.txt'
sudo systemctl start subject-hub
```

把 `/绝对数据目录` 换成服务使用的绝对路径；默认是仓库内的 `data/`。`setup-ubuntu.sh` 用安装用户运行服务；自定义 systemd 服务时，确认命令中的用户与服务账号一致。该命令让服务账号创建文件并设为仅该账号可读写，不会生成 root 所有、服务无法读取的密钥文件。轮换后所有旧登录会话失效，管理员和学生需要重新登录。若怀疑模型密钥也曾暴露，应到模型服务提供方轮换该密钥。不要把密钥贴到题目、Git 或聊天记录里。

不装 systemd、当前终端前台跑：

```bash
./scripts/run-ubuntu.sh
```

## 服务开关

```bash
systemctl status subject-hub
sudo systemctl start subject-hub
sudo systemctl stop subject-hub
sudo systemctl restart subject-hub
journalctl -u subject-hub -e
```

## 从 GitHub 更新

如果主机还在运行旧版，先不要把 8090 暴露给公网或不可信设备。旧版更新脚本本身不含当前保护；首次升级须先从 `origin/main` 取出新版脚本，在同一 checkout 执行（假设本地主机 `main` 跟踪 `origin/main`）：

```bash
cd ~/subject-hub
git fetch origin main && git show origin/main:scripts/update-from-github.sh > scripts/.first-safe-upgrade.sh && bash scripts/.first-safe-upgrade.sh
```

升级成功后删除临时脚本：

```bash
rm scripts/.first-safe-upgrade.sh
```

首次回退可能切回旧版并使新回退脚本从磁盘移走；已经由 Bash 打开的回退脚本仍会继续执行到结束，不要中断该 shell。

后续更新使用当前 checkout 的脚本：

```bash
cd ~/subject-hub
./scripts/update-from-github.sh
```

网页「重新读取本机题库」只重读主机磁盘上的 `bank/` 和 `data/local-bank/`，不访问 GitHub。要取得代码或仓库题库更新，必须在主机仓库运行上面的升级脚本。

升级脚本会先在隔离目录安装依赖、运行 Python 测试和前端类型检查/测试/构建；这些步骤通过后才停服、备份并验证当前实际数据目录，然后快进切换版本。升级前若有已跟踪文件改动或远端不能快进，脚本会停止并要求先自行保存或处理。启动后脚本检查健康接口；切换前失败会保留旧版本，切换后启动或健康检查失败则停服并打印升级备份和旧版目录。

升级成功后请保存终端打印的**升级前备份路径**与**旧版目录路径**。回退时使用脚本打印的旧版目录（路径需原样保留引号）：

```bash
./scripts/rollback-ubuntu.sh '更新输出的旧版目录'
```

回退会先停止服务、备份升级后的数据，再恢复升级前的数据和旧版运行环境。升级后的数据会另行保留。若自定义了答题端口，更新前设置 `SUBJECT_HUB_HEALTH_URL` 指向本机健康接口，例如 `http://127.0.0.1:8092/api/health`。

## 本地预览（Windows）

不装 Ubuntu 时可以在开发机本地预览网页；正式主机仍按 Ubuntu 步骤安装。Node.js 版本要求与上文相同。

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r backend\requirements.txt
cd frontend; npm ci; npm run build; cd ..
$env:PYTHONPATH = "$pwd\backend"
.\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8090
```

浏览器打开 `http://127.0.0.1:8090` 注册学生。家长在 `http://127.0.0.1:8091` 注册管理员，可以注册多位。网页 8090 上第一个注册的人**不是**管理员。

## 大模型入口

管理员登录后打开「模型」页配置出题和主观题评分共用的接口（默认 `http://127.0.0.1:8080/v1`）。设置保存在 `data/llm.env`；同名环境变量优先。若启动环境已设置模型地址或模型名，网页不能覆盖这些设置，应由装机人修改服务环境后重启。未配置时客观题照常判，主观题留待人工评分。

家长管理员只在本机 8091 注册，8090 上的注册一律是学生。

## 数据在哪

账号、成绩、家长导入或改过的本地题、演算纸照片、LLM 配置和会话签名文件都在服务实际使用的 `data/` 目录，不要进 Git。`git pull` 不会覆盖 `data/local-bank/` 里改过的题；同名题以本机为准，仓库里新加的题仍会进来。

备份会包含数据库、上传照片、题目、模型 API 密钥和会话签名文件，按敏感数据保管。备份目的目录的父目录必须已存在，目标备份目录必须是新的。先停服务，并确认没有其它进程写数据；`--service-stopped` 是操作者确认，不会代替检查服务状态。默认数据目录是仓库内的 `data/`（本例 checkout 在 `~/subject-hub` 时路径为 `~/subject-hub/data`）；若服务设置了 `SUBJECT_HUB_DATA`，必须使用那个实际路径。

```bash
cd ~/subject-hub
sudo systemctl stop subject-hub
systemctl is-active subject-hub   # 确认输出 inactive
python3 scripts/backup_restore.py backup --data-dir "$PWD/data" --output /安全存放位置/subject-hub-backup-日期 --service-stopped
python3 scripts/backup_restore.py verify --backup /安全存放位置/subject-hub-backup-日期
```

只有确认服务和其它写入进程都已停止后才做备份。`verify` 会核对备份清单、文件摘要和 SQLite 完整性；成功后可启动原服务。若接着轮换会话签名密钥，则保持服务停止，继续按上文命令操作。若使用自定义数据目录，把 `--data-dir` 换成该目录。

恢复时先验证备份，再恢复到**一个尚不存在的新目录**；恢复不会覆盖当前目录：

```bash
python3 scripts/backup_restore.py verify --backup /安全存放位置/subject-hub-backup-日期
python3 scripts/backup_restore.py restore --backup /安全存放位置/subject-hub-backup-日期 --output /安全存放位置/subject-hub-data-restored
```

该命令只生成恢复副本。检查完成后，由装机人将服务的数据路径切换到恢复目录再启动；不要先删除或覆盖原数据目录。
