# DPS Studio Windows Quick Start

_For users comfortable with Windows command prompts. See the [beginner guide](WINDOWS_BEGINNER_INSTALL_GUIDE.md) for explanations and troubleshooting._

---

## 🚀 Install and launch

1. Install current **Miniconda for Windows x86_64** from [Anaconda](https://www.anaconda.com/download/success), using the normal per-user location.
2. Clone the repository or use GitHub **Code → Download ZIP**; extract it to a short writable path such as `D:\DPS_Studio`.
3. Open **Miniconda Prompt** and run:

```powershell
cd /d D:\DPS_Studio
conda env create -f environment.yml
conda activate dps-studio
python -m pip install -e .
python -m dps_studio.gui
```

For later launches:

```powershell
cd /d D:\DPS_Studio
conda activate dps-studio
python -m dps_studio.gui
```

After a standard Miniconda installation, `run_pdv_studio_gui.bat` can be double-clicked as a convenience launcher.

## ⚠️ Important limit

The repository intentionally has no public example CSV. Installation and GUI startup can be completed from a clone, but a real analysis needs an authorized measurement file. `run_demo_pipeline.bat` is for local production data, not a public demo.

