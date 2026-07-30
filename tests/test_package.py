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


def test_only_unimplemented_future_packages_are_absent() -> None:
    """Reserved packages remain absent until their owning sessions implement them."""
    for name in ("arcadia.analysis", "arcadia.tools"):
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


def test_import_arcadia_does_not_import_hardware() -> None:
    """import arcadia must not eagerly import arcadia.hardware."""
    result = subprocess.run(
        [sys.executable, "-c", "import arcadia; import sys; print('arcadia.hardware' in sys.modules)"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert result.stdout.strip() == "False", "arcadia.hardware was eagerly imported"


def test_hardware_imports_no_forbidden_modules_or_probes() -> None:
    """Hardware import stays isolated and performs no subprocess probe."""
    forbidden = [
        "arcadia.config",
        "arcadia.events",
        "arcadia.storage",
        "arcadia.services",
        "arcadia.backends",
        "arcadia.transport",
        "arcadia.inference",
        "arcadia.tools",
        "arcadia.analysis",
        "arcadia.cli",
        "torch",
        "llama_cpp",
        "mlx",
    ]
    command = (
        "import subprocess; "
        "subprocess.run = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('probe')); "
        "import arcadia.hardware; import sys; "
        f"print([m for m in {forbidden!r} if m in sys.modules])"
    )
    result = subprocess.run([sys.executable, "-c", command], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert result.stdout.strip() == "[]", f"forbidden modules were imported: {result.stdout}"


def test_import_arcadia_does_not_import_services() -> None:
    """The root package remains independent from the lifecycle layer."""
    result = subprocess.run(
        [sys.executable, "-c", "import arcadia; import sys; print('arcadia.services' in sys.modules)"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert result.stdout.strip() == "False", "arcadia.services was eagerly imported"


def test_services_imports_without_heavy_or_future_backends() -> None:
    """Importing the generic lifecycle package performs no runtime backend work."""
    forbidden = HEAVY_MODULES + ["arcadia.backends", "arcadia.transport", "arcadia.inference", "arcadia.analysis"]
    command = (
        "import socket, threading; "
        "socket.create_connection = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('probe')); "
        "threading.Thread.start = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('thread')); "
        "import arcadia.services; import sys; "
        f"print([m for m in {forbidden!r} if m in sys.modules])"
    )
    result = subprocess.run([sys.executable, "-c", command], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert result.stdout.strip() == "[]", f"forbidden modules were imported: {result.stdout}"
