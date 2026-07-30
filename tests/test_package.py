"""Package import and lightweight-installation tests.

These tests verify the Session 0 contract:
- ``import arcadia`` succeeds after installation.
- ``arcadia.__version__`` equals ``0.1.0``.
- Importing ``arcadia`` does not import heavy modules.

The heavy-import test runs in a subprocess to guarantee a clean interpreter.
"""

import subprocess
import sys

import pytest

HEAVY_MODULES = [
    "django",
    "fastapi",
    "uvicorn",
    "cv2",
    "torch",
    "ultralytics",
    "llama_cpp",
]


def test_import_succeeds() -> None:
    """Importing the base package must succeed after installation."""
    import arcadia

    assert arcadia is not None


def test_version() -> None:
    """The package version must equal 0.1.0."""
    import arcadia

    assert arcadia.__version__ == "0.1.0"


def test_no_heavy_imports() -> None:
    """Importing arcadia must not pull in heavy dependencies.

    Runs in a fresh subprocess so ``sys.modules`` reflects only what
    ``import arcadia`` actually triggers.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import arcadia; import sys; print([m for m in {HEAVY_MODULES!r} if m in sys.modules])",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert result.stdout.strip() == "[]", f"heavy modules were imported: {result.stdout}"


def test_no_future_implementation_packages() -> None:
    """Session 0 must not create empty future implementation packages.

    These submodules are reserved for future sessions and must not exist yet.
    """
    for name in ("arcadia.services", "arcadia.analysis", "arcadia.tools"):
        with pytest.raises(ImportError, match=f"No module named '{name}'"):
            __import__(name)


def test_package_versions_match() -> None:
    """The code-level __version__ must match the installed package metadata."""
    from importlib.metadata import version as get_version

    import arcadia

    assert arcadia.__version__ == get_version("arcadia-core")


def test_import_arcadia_does_not_import_config() -> None:
    """import arcadia must not eagerly import arcadia.config."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import arcadia; import sys; print('arcadia.config' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert result.stdout.strip() == "False", "arcadia.config was eagerly imported"


def test_import_arcadia_does_not_import_events() -> None:
    """import arcadia must not eagerly import arcadia.events."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import arcadia; import sys; print('arcadia.events' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert result.stdout.strip() == "False", "arcadia.events was eagerly imported"


def test_import_arcadia_does_not_import_storage() -> None:
    """import arcadia must not eagerly import arcadia.storage."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import arcadia; import sys; print('arcadia.storage' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert result.stdout.strip() == "False", "arcadia.storage was eagerly imported"


def test_config_imports_no_heavy_or_future_modules() -> None:
    """arcadia.config must not import heavy libraries or future runtime modules."""
    forbidden = [
        "arcadia.services",
        "arcadia.events",
        "arcadia.storage",
        "arcadia.hardware",
        "arcadia.backends",
        "arcadia.transport",
        "arcadia.inference",
        "arcadia.analysis",
        "arcadia.tools",
    ]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import arcadia.config; import sys; print([m for m in {forbidden!r} if m in sys.modules])",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert result.stdout.strip() == "[]", f"future modules were imported: {result.stdout}"


def test_events_imports_no_forbidden_runtime_modules() -> None:
    """Importing arcadia.events stays below the runtime module layers."""
    forbidden = [
        "arcadia.config",
        "arcadia.storage",
        "arcadia.hardware",
        "arcadia.services",
        "arcadia.backends",
        "arcadia.transport",
        "arcadia.inference",
        "arcadia.analysis",
        "arcadia.tools",
        "arcadia.cli",
    ]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import arcadia.events; import sys; print([m for m in {forbidden!r} if m in sys.modules])",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert result.stdout.strip() == "[]", f"forbidden modules were imported: {result.stdout}"


def test_storage_imports_no_forbidden_runtime_modules() -> None:
    """Importing arcadia.storage stays below the runtime layers."""
    forbidden = [
        "arcadia.config",
        "arcadia.events",
        "arcadia.hardware",
        "arcadia.services",
        "arcadia.backends",
        "arcadia.transport",
        "arcadia.inference",
        "arcadia.analysis",
        "arcadia.tools",
        "arcadia.cli",
    ]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import arcadia.storage; import sys; print([m for m in {forbidden!r} if m in sys.modules])",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert result.stdout.strip() == "[]", f"forbidden modules were imported: {result.stdout}"
