import json
import os
import shutil
import subprocess
import time
from pathlib import Path


class MinerURuntime:
    def __init__(self, project_root):
        self.project_root = Path(project_root)
        self.venv_root = self.project_root / ".venv_mineru"
        self.scripts_dir = self.venv_root / "Scripts"
        self.mineru_cli = self._find_cli("mineru.exe", "mineru")
        self.models_download_cli = self._find_cli("mineru-models-download.exe", "mineru-models-download")
        self.config_path = Path.home() / "mineru.json"

    def status(self):
        return {
            "venv_root": str(self.venv_root),
            "mineru_cli": str(self.mineru_cli) if self.mineru_cli else None,
            "models_download_cli": str(self.models_download_cli) if self.models_download_cli else None,
            "config_path": str(self.config_path),
            "config_exists": self.config_path.exists(),
            "models_dir": self._read_models_dir(),
        }

    def ensure_models(self, source="modelscope", model_type="pipeline"):
        if not self.models_download_cli:
            return {
                "success": False,
                "error": "mineru-models-download CLI not found"
            }

        env = self._build_env()
        env["MINERU_MODEL_SOURCE"] = source
        command = [str(self.models_download_cli), "-s", source, "-m", model_type]
        completed = subprocess.run(command, capture_output=True, text=True, env=env, timeout=1800)
        return {
            "success": completed.returncode == 0,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "returncode": completed.returncode,
            "models_dir": self._read_models_dir(),
        }

    def run_parse(self, pdf_path, output_dir, method="txt", backend="pipeline"):
        if not self.mineru_cli:
            return {
                "success": False,
                "error": "mineru CLI not found"
            }

        pdf_path = Path(pdf_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        env = self._build_env()
        env["MINERU_MODEL_SOURCE"] = "local"
        command = [
            str(self.mineru_cli),
            "-p",
            str(pdf_path),
            "-o",
            str(output_dir),
            "-m",
            method,
            "-b",
            backend,
        ]
        completed = subprocess.run(command, capture_output=True, text=True, env=env, timeout=1800)
        markdown_path = self._wait_for_markdown(output_dir, pdf_path.stem)
        return {
            "success": completed.returncode == 0 and markdown_path is not None,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "markdown_path": str(markdown_path) if markdown_path else None,
            "output_dir": str(output_dir),
        }

    def _build_env(self):
        env = os.environ.copy()
        env["PATH"] = str(self.scripts_dir) + os.pathsep + env.get("PATH", "")
        return env

    def _find_cli(self, local_name, fallback_name):
        local_path = self.scripts_dir / local_name
        if local_path.exists():
            return local_path
        fallback = shutil.which(fallback_name)
        return Path(fallback) if fallback else None

    def _read_models_dir(self):
        if not self.config_path.exists():
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as file_obj:
                data = json.load(file_obj)
            return data.get("models-dir", {})
        except Exception:
            return {}

    def _find_markdown(self, output_dir, stem):
        exact = output_dir / stem / "txt" / f"{stem}.md"
        if exact.exists():
            return exact
        for candidate in output_dir.rglob("*.md"):
            return candidate
        return None

    def _wait_for_markdown(self, output_dir, stem, timeout_seconds=45):
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            markdown_path = self._find_markdown(output_dir, stem)
            if markdown_path is not None:
                return markdown_path
            time.sleep(1)
        return self._find_markdown(output_dir, stem)


mineru_runtime = MinerURuntime(project_root=Path(__file__).resolve().parents[3])
