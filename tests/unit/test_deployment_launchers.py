from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_gui_launcher_uses_portable_conda_discovery() -> None:
    launcher = (REPOSITORY_ROOT / "run_pdv_studio_gui.bat").read_text(encoding="utf-8")

    assert "D:\\miniconda3" not in launcher
    assert "%USERPROFILE%\\miniconda3\\Scripts\\conda.exe" in launcher
    assert "DPS_STUDIO_CONDA_ENV" in launcher
    assert "python -m dps_studio.gui" in launcher


def test_production_launcher_does_not_pin_the_author_python_path() -> None:
    launcher = (REPOSITORY_ROOT / "run_demo_pipeline.bat").read_text(encoding="utf-8")

    assert "D:\\miniconda3\\envs\\dps-studio\\python.exe" not in launcher
    assert "conda" in launcher.lower()
    assert "DPS_STUDIO_CONDA_ENV" in launcher
