# SPDX-License-Identifier: GPL-3.0-only

import math

import pytest

from xcos_mcp.process import scilab_string, validate_timeout


def test_scilab_string_escapes_path_metacharacters():
    assert scilab_string('a\\b"c') == 'a\\b""c'


@pytest.mark.parametrize("timeout", [0, -2, math.inf, math.nan, "10"])
def test_timeout_validation(timeout):
    with pytest.raises(ValueError):
        validate_timeout(timeout)
