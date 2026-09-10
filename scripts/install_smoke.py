"""Install built wheel into a fresh environment with no runtime extras; run from any OS."""

import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)


def main() -> None:
    wheels = sorted((ROOT / "dist").glob("coherent_verdi_control-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("build one unambiguous current wheel into dist/ first")
    scratch = ROOT / "tmp"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="install-smoke-", dir=scratch) as directory:
        env_path = Path(directory) / "env"
        venv.EnvBuilder(with_pip=True).create(env_path)
        executable = env_path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run([str(executable), "-m", "pip", "install", "--no-deps", "--no-index", str(wheels[0])])
        # CWD outside source and isolated mode prove this imports the installed wheel.
        check = run(
            [
                str(executable),
                "-I",
                "-c",
                "import coherent_verdi, sys; from pathlib import Path; "
                "assert 'serial' not in sys.modules; assert 'dash' not in sys.modules; "
                "assert Path(coherent_verdi.__file__).parent.joinpath('py.typed').exists(); "
                "assets = Path(coherent_verdi.__file__).parent / 'assets'; "
                "assert assets.joinpath('style.css').exists(); "
                "assert assets.joinpath('watchdog.js').exists(); "
                "print(coherent_verdi.__file__)",
            ],
            cwd=directory,
        )
        cli = run(
            [str(executable), "-I", "-m", "coherent_verdi", "--demo", "status"], cwd=directory
        )
        data = json.loads(cli.stdout)
        assert data["simulated"] is True and data["result"]["power_w"] == 1.0
        for example in ("simulated_session.py", "async_integration.py"):
            run([str(executable), "-I", str(ROOT / "examples" / example)], cwd=directory)
        entrypoint = env_path / ("Scripts/verdi.exe" if os.name == "nt" else "bin/verdi")
        result = json.loads(run([str(entrypoint), "query", "?SV"], cwd=directory).stdout)
        assert result["result"] == "SIMULATOR-0.1"
        print(
            "PASS: clean wheel install, entrypoint, CLI, both examples, optional extras absent\n"
            f"Installed module: {check.stdout.strip()}"
        )


if __name__ == "__main__":
    main()
