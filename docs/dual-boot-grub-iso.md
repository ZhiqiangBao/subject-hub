# 附属：用 GRUB 和本地 ISO 做 Windows / Ubuntu 双系统

给家里管理员看，不是学生或家长用的说明。目的：同一台电脑保留 Windows（日常、写作业），再装 Ubuntu 跑学科 Hub。安装介质用**已经下载到硬盘上的 ISO**，通过 **GRUB 配置文件** 引导安装，不一定要 U 盘。

有现成的 Ubuntu 安装器 U 盘时，用 U 盘更省事，不必走本页。下面只写「硬盘上已有 ISO + 改 GRUB」这条路。

## 事前

- 备份重要数据。改分区、装系统都可能丢掉盘上的文件。
- 准备官方 Ubuntu 桌面或服务器 ISO（amd64），放到**安装过程中不会被格式化**的分区。不要放在打算划给 Ubuntu 的空分区上。
- Windows 若开了 BitLocker，先暂停加密，再缩小卷。
- 记下 ISO 的全路径和它所在分区。UEFI 机器上看分区号：现有 Linux 里 `sudo fdisk -l` 或 `lsblk -f`；只有 Windows 时用磁盘管理看盘符，装好 GRUB 后再对 `hd0,gptN`。

ISO 放在 ext4 / FAT 上最省事。放在 NTFS 上需要 GRUB 能加载 `ntfs` 模块，有的环境会失败，那时把 ISO 拷到 FAT 分区再试。

## 已有 Ubuntu / GRUB 时：加一条 ISO 启动项

用自定义文件，不要手改生成出来的 `grub.cfg`（下次 `update-grub` 会被覆盖）。

编辑 `/etc/grub.d/40_custom`，在文件末尾追加（路径、分区、ISO 文件名改成你的）：

```bash
#!/bin/sh
exec tail -n +3 $0

menuentry "Ubuntu ISO（安装 / 试用）" {
    insmod part_gpt
    insmod ext2
    insmod iso9660
    set isofile="/iso/ubuntu-24.04.x-desktop-amd64.iso"
    loopback loop (hd0,gpt5)$isofile
    linux (loop)/casper/vmlinuz boot=casper iso-scan/filename=$isofile noprompt ---
    initrd (loop)/casper/initrd
}
```

说明：

- `(hd0,gpt5)` 换成 ISO 所在分区。GPT 磁盘是 `gptN`，老 MBR 是 `msdosN`。编号以 GRUB 为准，可在 GRUB 命令行 `ls` 查看。
- `isofile` 是该分区里的路径，以 `/` 开头，不是 Windows 的 `D:\...`。
- 较新的桌面 ISO 内核一般是 `(loop)/casper/vmlinuz` 和 `(loop)/casper/initrd`。若启动报找不到文件，把 ISO 当光盘挂上后看 `casper/` 里的实际名字（有的带 `.efi` 后缀）。
- `iso-scan/filename=` 必须与 `isofile` 一致，否则安装器找不到镜像。
- 若 ISO 在 NTFS：在 `insmod ext2` 旁加 `insmod ntfs`，分区类型对不上就换分区。

然后：

```bash
sudo chmod +x /etc/grub.d/40_custom
sudo update-grub
```

重启，在 GRUB 菜单选 **Ubuntu ISO（安装 / 试用）**，进入安装器。安装时把 Ubuntu 装到**事先划出的空闲分区**，不要格式化存放 ISO 的那个分区，也不要误删 Windows 分区。

装好后进新系统执行一次 `sudo update-grub`。开着 `os-prober` 时一般会自动出现 **Windows** 项。以后日常开机用菜单选 Ubuntu（跑测评）或 Windows（学生/家长日常）。

安装成功后从 `40_custom` 删掉 ISO 这一条，再 `update-grub`，避免每次开机多一个无用项。ISO 文件可以留着或删掉。

## 现在只有 Windows：先让本机有一份 GRUB，再引导 ISO

Windows 本身不读 `grub.cfg`。需要先有一个能加载本地 ISO 的 GRUB（例如 [GRUB2Win](https://sourceforge.net/projects/grub2win/) 这类装在 EFI 分区上的引导，或临时用已有 Linux 的 GRUB）。

思路相同：把 ISO 放到某个盘（建议单独一个小 FAT 分区），在 GRUB 的自定义 `grub.cfg` / 菜单文件里写与上一节相同的 `menuentry`（`loopback` + `casper` + `iso-scan/filename`）。保存后从固件启动菜单选这个 GRUB，再选 ISO 项，进入安装器。

分区建议：在磁盘管理里从 Windows 盘末尾压缩出空间，安装器里在这片空闲上建 Ubuntu 的 `ext4` 根分区；EFI 分区沿用已有 ESP，让安装器把 GRUB 写进 EFI。不要选「擦除整块磁盘」。

GRUB 菜单文件改错导致无法开机时：用 Ubuntu ISO 再进一次试用，挂上 EFI 和根分区，`chroot` 后 `update-grub` / `grub-install`，或在 Windows 里用安装媒介执行 `bcdboot` 先救回 Windows 启动，再修 Ubuntu。

## 和学科 Hub 的关系

双系统只解决「这台机子上同时有 Windows 和 Ubuntu」。学科 Hub 的服务装在 **Ubuntu** 里，学生和家长用浏览器访问局域网地址，不必进 GRUB、不必碰 ISO。

建议开机默认项设成 Ubuntu（测评常开），Windows 偶尔用时在 GRUB 里选。不要两个系统各装一份学科 Hub 还共用成绩库。

## 不要做的事

- 把 ISO 放在即将格式化成 Ubuntu 根分区的位置。
- 直接编辑 `/boot/grub/grub.cfg` 当长期配置。
- 在未备份、未暂停 BitLocker 时强行压缩 Windows 分区。
- 把本页步骤发给学生当「如何答题」。
