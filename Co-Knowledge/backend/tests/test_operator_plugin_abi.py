"""Operator plugin ABI v2: public imports and legacy rejection."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from shared.errors.api import KbApiError
from operators.service.operator_import import (TEMPLATE_DIR,
                                                validate_plugin_abi,
                                                validate_script)


def _write(tmp_path: Path, source: str) -> Path:
    path = tmp_path / 'operator.py'
    path.write_text(source, encoding='utf-8')
    return path


def test_operator_api_imports_are_accepted(tmp_path):
    path = _write(tmp_path, (
        'from operator_api.llm import invoke_llm\n'
        'from operator_api.logging import TxPrefixedLogger\n'
        'from operator_api.storage import read_text\n'
        'from operator_api.types import Chunk\n'
    ))

    validate_plugin_abi(path)


@pytest.mark.parametrize('module', ['client.graph_checker', 'utility.txlog',
                                    'service.file', 'split.system_split',
                                    'doc_pipeline.runtime'])
def test_legacy_plugin_imports_are_rejected(tmp_path, module):
    path = _write(tmp_path, f'from {module} import thing\n')

    with pytest.raises(KbApiError) as caught:
        validate_plugin_abi(path)

    assert caught.value.key == 'operator.plugin.incompatible'


def test_import_validation_rejects_legacy_graph_operator(tmp_path):
    path = _write(tmp_path, 'from client.graph_checker import GraphChecker\n')

    with pytest.raises(KbApiError) as caught:
        validate_script(path, {'module': 'graph_extract', 'defaultArgs': []})

    assert caught.value.key == 'operator.plugin.incompatible'


def test_project_root_imports_are_not_flagged(tmp_path):
    """``operator_api`` is the new ABI; a package whose name merely starts with
    a legacy prefix (none exist today) must not be rejected by prefix matching."""
    path = _write(tmp_path, (
        'import json\n'
        'from operator_api import llm\n'
        'from operator_api.graph import GraphChecker\n'
    ))

    validate_plugin_abi(path)


def test_bundled_graph_template_uses_v2_abi():
    """The shipped graph-extraction template must import only the public ABI."""
    template = TEMPLATE_DIR / 'graph_extract.zip'
    with zipfile.ZipFile(template) as archive:
        source = archive.read('graph_extract/graph_extract.py').decode('utf-8')

    assert 'operator_api.graph' in source
    assert 'operator_api.logging' in source
    assert 'operator_api.llm' in source
    assert 'from client.' not in source
    assert 'from utility.' not in source
