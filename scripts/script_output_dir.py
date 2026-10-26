"""Print the output folder name (inside generated/) for a script file; used by the GitHub workflow.

    PYTHONPATH=. python scripts/script_output_dir.py scripts/my_video.yaml lively
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import src  # noqa: F401,E402
from src.config.settings import load_settings  # noqa: E402
from src.script_mode.runner import output_dir  # noqa: E402
from src.script_mode.schema import load_user_script  # noqa: E402

if __name__ == "__main__":
    style = sys.argv[2] if len(sys.argv) > 2 else "lively"
    print(output_dir(load_settings(), load_user_script(sys.argv[1]).title, style).name)
