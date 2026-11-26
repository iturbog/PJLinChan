"""PJLinChan ビルドスクリプト

使い方（プロジェクトのルートで）:
    .\\.venv\\Scripts\\python.exe build_pjlc.py

dist/PJLinChan_v<VERSION>.exe が生成される。
image / locale は exe に内蔵される。
"""
import os
import re
import sys

import PyInstaller.__main__

ROOT = os.path.dirname(os.path.abspath(__file__))
SEP = os.pathsep  # Windows: ";"  macOS/Linux: ":"


def read_version():
    """main.py の VERSION = "x.xx" を読み取る"""
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', f.read(), re.MULTILINE)
    if not m:
        sys.exit("main.py から VERSION を読み取れませんでした")
    return m.group(1)


def main():
    os.chdir(ROOT)
    version = read_version()
    name = f"PJLinChan_v{version}"
    args = [
        "main.py",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", name,
        "--add-data", f"image{SEP}image",
        "--add-data", f"locale{SEP}locale",
        "--collect-all", "customtkinter",
        # Linux では PIL.ImageTk が内部で使うこのモジュールが自動検出されず、画像表示で失敗する
        "--hidden-import", "PIL._tkinter_finder",
    ]

    # 実行ファイルのアイコンは Windows(.ico) / macOS(.icns) のみ対応
    if sys.platform == "darwin":
        args += ["--icon", os.path.join("image", "icon.icns")]
    elif os.name == "nt":
        args += ["--icon", os.path.join("image", "icon.ico")]

    print(f"=== Building {name} ===")
    PyInstaller.__main__.run(args)
    print(f"=== Done: dist/{name}{'.exe' if os.name == 'nt' else ''} ===")


if __name__ == "__main__":
    main()
