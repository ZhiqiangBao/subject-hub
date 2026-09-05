# 评测主机：安装与更新

给家里装机的人看。学生和家长只用浏览器打开网页。

服务名 `subject-hub`。答题端口 **8090**（局域网打开）。家长后台端口 **8091**，只绑在本机 `127.0.0.1`，用来注册管理员；可以注册多位家长。

## 第一次安装

依赖：Ubuntu、`python3`、Node.js / npm。

```bash
git clone https://github.com/ZhiqiangBao/subject-hub.git
cd subject-hub
chmod +x scripts/setup-ubuntu.sh scripts/run-ubuntu.sh scripts/update-from-github.sh
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

```bash
cd ~/subject-hub
./scripts/update-from-github.sh
```

只更新了 `bank/` 时，家长在网页点「更新题库」也会尝试拉取；拉不到时再在主机跑上面这条。

## 本机自测（Windows）

不装 Ubuntu 时也可以先看网页：

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r backend\requirements.txt
cd frontend; npm install; npm run build; cd ..
$env:PYTHONPATH = "$pwd\backend"
.\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8090
```

浏览器打开 `http://127.0.0.1:8090` 注册学生。家长在 `http://127.0.0.1:8091` 注册管理员，可以注册多位。网页 8090 上第一个注册的人**不是**管理员。

## 大模型入口

管理员登录后打开「模型」页即可接到本机对话接口（默认 `http://127.0.0.1:8080/v1`），也可手写 `data/llm.env`。未配置时客观题照常判，主观题留给管理员手打。

家长管理员只在本机 8091 注册，8090 上的注册一律是学生。

## 数据在哪

账号、成绩、家长导入或改过的本地题、演算纸照片都在仓库旁的 `data/`，不要进 Git。`git pull` 不会覆盖 `data/local-bank/` 里改过的题；同名题以本机为准，仓库里新加的题仍会进来。
