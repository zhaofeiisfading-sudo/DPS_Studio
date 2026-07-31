"""Render TASK-014 screenshots from the real Qt window."""

from pathlib import Path

from PySide6.QtCore import Qt

from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.main_window import MainWindow


def main() -> None:
    output_directory = Path(__file__).resolve().parent
    application = create_application([], language_code="zh_CN")
    for language_code, filename, capture_width, capture_height in (
        ("zh_CN", "main_window_zh.png", 1440, 900),
        ("en", "main_window_en.png", 1440, 900),
        ("zh_CN", "layout_check_1280x720_zh.png", 1280, 720),
    ):
        translation_manager().install(language_code)
        window = MainWindow(translation_manager=translation_manager())
        # The native Windows frame consumes 20 logical vertical pixels. Capture
        # the requested client area, then normalize the high-DPI backing image.
        window.resize(capture_width, capture_height + 20)
        window.show()
        application.processEvents()
        image = window.grab().scaled(
            capture_width,
            capture_height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        output_path = output_directory / filename
        if not image.save(str(output_path), "PNG"):
            raise RuntimeError(f"Could not save screenshot: {output_path}")
        print(f"{output_path}: {image.width()}x{image.height()}")
        window.close()
        application.processEvents()


if __name__ == "__main__":
    main()
