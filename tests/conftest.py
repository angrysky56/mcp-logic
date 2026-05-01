import os
import subprocess
from pathlib import Path

import pytest


def discover_ladr():
    """Discover the LADR binary path (Prover9/Mace4)."""
    # 1. Environment variable
    env_path = os.environ.get("LADR_PATH")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path

    # 2. Local directory
    local_path = Path(__file__).parent.parent / "ladr" / "bin"
    if local_path.exists():
        return local_path

    # 3. System path (check for prover9)
    try:
        result = subprocess.run(["which", "prover9"], capture_output=True, text=True)
        if result.returncode == 0:
            return Path(result.stdout.strip()).parent
    except Exception:
        pass

    return None


LADR_PATH = discover_ladr()


def has_prover9():
    if not LADR_PATH:
        return False
    exe = LADR_PATH / "prover9"
    if not exe.exists():
        exe = LADR_PATH / "prover9.exe"
    return exe.exists()


def has_mace4():
    if not LADR_PATH:
        return False
    exe = LADR_PATH / "mace4"
    if not exe.exists():
        exe = LADR_PATH / "mace4.exe"
    return exe.exists()


@pytest.fixture(scope="session")
def prover_path():
    return LADR_PATH


@pytest.fixture(scope="session")
def prover_available():
    return has_prover9()


@pytest.fixture(scope="session")
def mace4_available():
    return has_mace4()
