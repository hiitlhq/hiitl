"""The version hiitl reports is the version it is published at.

The version is written once, in `hiitl/_version.py`. Every place the package states it reads that one copy: the
package's `__version__`, the sync client's header (test_sync.py), the telemetry record (test_telemetry.py), the MCP
proxy's server info, the synthetic runner's report, and the build (pyproject.toml), so a wheel cannot be published at
one version while reporting another.
"""

from pathlib import Path

import pytest

import hiitl
from hiitl._version import __version__


def test_the_package_exports_the_one_version():
    assert hiitl.__version__ == __version__


def test_the_mcp_proxy_announces_the_package_version():
    pytest.importorskip("mcp")
    from hiitl.mcp_proxy.proxy import PROXY_SERVER_VERSION

    assert PROXY_SERVER_VERSION == __version__


def test_the_synthetic_runner_reports_the_package_version():
    from hiitl.synthetic.types import RunReport

    assert RunReport.model_fields["runner_version"].default == __version__


def test_the_build_reads_the_version_from_the_one_copy():
    """setuptools' dynamic metadata (`attr:`) reads `hiitl._version.__version__`; a static `version` beside it would
    be a second copy, and the wheel would carry it."""
    tomllib = pytest.importorskip("tomllib")
    pyproject = Path(hiitl.__file__).resolve().parents[1] / "pyproject.toml"
    if not pyproject.is_file():
        pytest.skip("installed from a wheel: no pyproject.toml beside the package")
    meta = tomllib.loads(pyproject.read_text())

    assert "version" not in meta["project"]
    assert "version" in meta["project"]["dynamic"]
    assert meta["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "hiitl._version.__version__"}
