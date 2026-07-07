"""CommitShrink: a perfectly serious developer mental-health assessment from git log."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    # Single source of truth: read the version from the installed package
    # metadata (populated from pyproject.toml), so __version__ and the
    # distribution version can never drift apart.
    __version__ = _pkg_version("commit-shrink")
except PackageNotFoundError:  # not installed (e.g. running from a bare checkout)
    __version__ = "0.0.0+unknown"
