"""An unsupported resource must be reported as such, not as a config problem.

Regression from live verification against Gitea 1.27: asking for a GitLab-only
resource produced `Error: Missing required key or environment variable: "..."`.
The real explanation was inside the quotes, but the headline sent the reader
hunting a config/env problem that did not exist.
"""

from __future__ import annotations

import pytest

from cicd_aiops.platform import UnsupportedResource, get_platform


@pytest.mark.unit
def test_unsupported_resource_is_its_own_error_type():
    plat = get_platform("gitea")
    with pytest.raises(UnsupportedResource) as ei:
        plat.path("runners")
    msg = str(ei.value)
    assert "not available on platform 'gitea'" in msg
    assert "Available resources:" in msg


@pytest.mark.unit
def test_unsupported_resource_still_behaves_as_keyerror():
    """Subclassing KeyError keeps existing `except KeyError` handlers working."""
    plat = get_platform("gitea")
    with pytest.raises(KeyError):
        plat.path("runners")


@pytest.mark.unit
def test_cli_does_not_relabel_it_as_a_missing_config_key():
    from cicd_aiops.cli import _common

    @_common.cli_errors
    def boom():
        raise UnsupportedResource("Resource 'runners' is not available on platform 'gitea'.")

    import typer

    with pytest.raises(typer.Exit):
        boom()
