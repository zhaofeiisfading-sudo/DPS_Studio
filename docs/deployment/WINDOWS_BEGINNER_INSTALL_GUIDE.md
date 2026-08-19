# DPS Studio Windows 零基础安装与运行教程

_面向 Windows 10/11 64 位用户。仓库没有可公开分发的示例 CSV：可以完成安装和启动 GUI，第一次分析需要你有权使用的数据文件。_

---

## 🧭 第 0 步：开始前确认

你需要网络、约 3 GB 空闲空间和一个可写文件夹。推荐 `D:\DPS_Studio`；没有 D 盘可用 `C:\DPS_Studio`。不必使用作者电脑的路径。

**Miniconda** 是管理 Python 的小工具；**环境** 是 DPS Studio 自己独立的一套 Python 和软件包；**pip** 是安装 Python 软件的命令；**GitHub 仓库** 是项目文件所在的网站；**GUI** 是带按钮的图形窗口。

## 📥 第 1 步：下载项目

现在做什么：从作者给你的 GitHub 页面点绿色 **Code** → **Download ZIP**，下载完成后右键 ZIP → “全部解压缩”。这是推荐方法，不需要会 Git。

成功时，解压后的实际项目目录中直接能看到 `environment.yml`、`pyproject.toml` 和 `src`。若看不到，请进入更深一层文件夹。会 Git 的用户也可以运行：

```powershell
git clone <REPOSITORY-URL> D:\DPS_Studio
```

ZIP 不影响软件运行，只是不保留 Git 更新历史。

## 📁 第 2 步：选择文件夹

把项目放到 `D:\DPS_Studio` 或 `C:\DPS_Studio`。不要放在临时 Downloads；短路径能减少 Windows 路径问题。成功时资源管理器地址栏显示该目录，并且里面直接有 `environment.yml`。

## 🧰 第 3 步：安装 Miniconda

现在做什么：安装 Python 环境管理工具。打开 [Miniconda Windows 安装说明](https://www.anaconda.com/docs/getting-started/miniconda/install#windows-installation)，下载 **Windows x86_64**，双击安装。

选择 **Just Me**，其余保持默认；不必安装到 `D:\miniconda3`，也不建议勾选 “Add Miniconda to my PATH”。安装结束后，从开始菜单打开 **Miniconda Prompt**。看到黑色命令窗口即成功。

## 📂 第 4 步：进入项目目录

在 Miniconda Prompt 输入并按 Enter：

```powershell
cd /d D:\DPS_Studio
```

这只是在告诉命令窗口进入项目目录。若项目在 C 盘，把 `D:` 改为 `C:`；提示找不到路径时，在资源管理器复制真实地址栏路径。

## 🧪 第 5 步：创建环境

现在做什么：下载 Python 3.12 和基础工具。为什么：让软件不与电脑其他 Python 项目冲突。

```powershell
conda env create -f environment.yml
```

下载和解析可能要几分钟，属正常现象。若出现 `Proceed ([y]/n)?`，输入 `y` 并按 Enter。网络失败时确认能访问 `conda-forge`，再重试。

## ▶️ 第 6 步：安装 DPS Studio

输入：

```powershell
conda activate dps-studio
python -m pip install -e .
```

成功时命令行前面会有 `(dps-studio)`，且安装末尾没有红色报错。第一条切换到项目专用环境；第二条才安装 GUI、NumPy、SciPy 和 Qt。始终用 `python -m pip`，避免把软件装到错误 Python。

## ✅ 第 7 步：自检和启动

```powershell
python --version
python -c "import dps_studio; print('DPS Studio import OK')"
python -m dps_studio.gui
```

成功时版本为 3.12.x，显示 `DPS Studio import OK`，随后打开标题为 **PDV Studio** 的窗口。以后也可双击根目录的 `run_pdv_studio_gui.bat`。

## 📊 第 8 步：第一次分析

仓库没有公开 demo CSV，因此不要期待解压后能立刻选择一个示例。使用你有权处理、至少有一列时间和一列电压的 CSV/文本文件：

1. 在“数据导入”页点“选择并导入数据…”或工具栏“打开数据…”
2. 选择文件，在导入对话框明确选择时间列、电压列、分隔符、表头和单位缩放
3. 看到日志报告加载行数/通道数后，保留默认科学参数
4. 在“分析”菜单选择“自动分析”，检查时频、脊线和结果页是否显示图与质量状态

GUI 能开但分析失败通常是数据列、单位或分析参数问题，不是安装问题；不要为消除报错而随意改动科学参数。

## 🔄 第 9 步：以后怎样启动

每次无需重装，只需：

```powershell
cd /d D:\DPS_Studio
conda activate dps-studio
python -m dps_studio.gui
```

## 🛠️ Troubleshooting：看到报错怎么办

### `conda` 或 `python` 不是内部或外部命令

关闭普通命令提示符，打开开始菜单的 **Miniconda Prompt**，再执行 `conda activate dps-studio`。不要手工修改 PATH 或打开 Microsoft Store Python。

### `No module named dps_studio` 或 `No module named PySide6`

运行：

```powershell
where python
python -m pip --version
```

两行都应指向 `dps-studio`。然后在项目根目录重做 `python -m pip install -e .`。

### `DLL load failed` 或 Qt platform plugin error

确认环境已激活，再运行 `python -m pip install -e .`。仍失败时记录完整报错、Windows 版本和 `python --version` 联系维护者；这是 Qt/系统库问题，不是科学分析问题。

### `CondaValueError: prefix already exists`

环境通常已经建好，直接运行 `conda activate dps-studio`。只有确认环境损坏时才执行 `conda env remove -n dps-studio` 后重建；该命令会删除环境。

### Git 未安装、路径不存在、或网络下载失败

Git 未安装就用 Download ZIP。路径不存在时从资源管理器复制真实路径。网络失败时检查网络/代理后重试；不要改用作者旧版 Miniconda。

## 🔗 参考

[^1]: Anaconda Documentation. “Miniconda installation.” https://www.anaconda.com/docs/getting-started/miniconda/install
[^2]: Conda Documentation. “conda env create.” https://docs.conda.io/projects/conda/en/stable/commands/env/create.html

