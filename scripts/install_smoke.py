"""Exercise built distributions in isolated core or optional-extras environments."""

import argparse
import json
import os
import subprocess
import tarfile
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)


def main(*, extras: bool = False) -> None:
    wheels = sorted((ROOT / "dist").glob("coherent_verdi_control-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("build one unambiguous current wheel into dist/ first")
    sources = sorted((ROOT / "dist").glob("coherent_verdi_control-*.tar.gz"))
    if len(sources) != 1:
        raise RuntimeError("build one unambiguous current sdist into dist/ first")
    with tarfile.open(sources[0]) as archive:
        members = {name.partition("/")[2] for name in archive.getnames()}
    required = {
        "scripts/validate.py",
        "scripts/install_smoke.py",
        "scripts/gui_smoke.py",
        "scripts/test_watchdog.cjs",
        "examples/simulated_session.py",
        "examples/async_integration.py",
        "tests/test_validation_runner.py",
        "src/coherent_verdi/py.typed",
        "src/coherent_verdi/assets/watchdog.js",
    }
    if missing := required - members:
        raise RuntimeError(f"source distribution lacks supporting files: {sorted(missing)}")
    scratch = ROOT / "tmp"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="install-smoke-", dir=scratch) as directory:
        env_path = Path(directory) / "env"
        venv.EnvBuilder(with_pip=True).create(env_path)
        executable = env_path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        install = [str(executable), "-m", "pip", "install"]
        install += (
            [f"{wheels[0]}[serial,gui]"] if extras else ["--no-deps", "--no-index", str(wheels[0])]
        )
        run(install)
        run([str(executable), "-m", "pip", "check"])
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
        if extras:
            smoke = run(
                [str(executable), "-I", str(ROOT / "scripts" / "gui_smoke.py")], cwd=directory
            )
            print(smoke.stdout.strip())
        else:
            missing_gui = subprocess.run(
                [str(executable), "-I", "-m", "coherent_verdi", "gui"],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert missing_gui.returncode == 2
            assert json.loads(missing_gui.stderr)["type"] == "ModuleNotFoundError"
        print(
            "PASS: sdist completeness, clean wheel install, entrypoint, CLI, both examples, "
            f"{'GUI/serial extras installed' if extras else 'optional extras absent'}\n"
            f"Installed module: {check.stdout.strip()}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extras", action="store_true", help="install GUI/serial extras from pip")
    main(extras=parser.parse_args().extras)
