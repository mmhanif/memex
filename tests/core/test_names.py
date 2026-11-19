"""SPEC §9.3: matching ignores case and accents."""

import pytest

from memex.core.names import fold
from tests.fold_cases import FOLD_CASES


@pytest.mark.parametrize(("text", "folded"), FOLD_CASES)
def test_fold_agrees_with_the_shared_cases(text: str, folded: str):
    assert fold(text) == folded
