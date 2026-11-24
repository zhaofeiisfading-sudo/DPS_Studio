# PDV Studio 安装与使用常见问题（FAQ）

### 1. 双击安装包提示“Windows 已保护你的电脑”怎么办？
当前安装包尚未配置商业数字签名（`NotSigned`）。在蓝色提示弹窗中点击 **更多信息 → 仍要运行** 即可正常安装，无需改动系统安全设置。

### 2. 为什么不能安装到 `C:\Program Files`，或提示目录不可写？
PDV Studio 为普通用户权限安装，并把配置和自定义材料集中保存在 `<安装目录>\userdata\`。`C:\Program Files` 默认对普通账户只读，请改选默认推荐的 `D:\Programs\PDV Studio` 或 `%LOCALAPPDATA%\Programs\PDV Studio` 等可写目录。

### 3. 终端输入 `pdv` 提示“找不到命令”怎么办？桌面一键脚本怎么用？
**CLI 已随软件安装，无需额外单独安装**，只是安装向导默认未勾选 PATH。**若终端无法直接输入 `pdv`，请按说明补加 PATH**：重新运行安装包覆盖同一目录并勾选 `Add command-line tool (pdv) to current user PATH`（重开终端生效），或按 [README_for_agent.md](README_for_agent.md) 中的 PowerShell 命令添加，也可直接运行 `"<安装目录>\pdv.exe"`。
如果不想开终端，可把安装目录 `launchers\`（或压缩包内）的两个 `.bat` 一键脚本复制到桌面，直接把 `.csv` / `.dat` 波形文件拖到脚本图标上即可全自动分析（要求文件为 2–4 列、`s`/`V`/`1550 nm`/`0°`）。

### 4. 如何切换语言？覆盖升级或卸载会丢数据吗？
打开软件后在顶部菜单 **设置 → 语言** 即可切换中文或英文。同目录覆盖升级会完整保留 `userdata/` 中的设置与自定义窗口材料；标准卸载时也会默认询问并保留 `userdata/`。

### 5. `velocity_gated.csv` 里为什么有空白单元格？能直接读 `.xlsx` 吗？
`velocity_gated.csv` 保留完整均匀时间网格，仅在质量未通过的帧留空（空白 `""` 而非 `"nan"` 文本），这样 Origin / Excel 可以直接识别为数值列并在缺口处自动断线；想直接连续画图请用 `velocity_display.csv`。目前不支持直接读取 `.xlsx`，请先在 Excel 中另存为 `.csv`、`.dat` 或 `.txt`（保留原工作簿）。
