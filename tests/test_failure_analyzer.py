import pytest
from server.evolution import FailureAnalyzer, Diagnosis


@pytest.fixture
def analyzer():
    return FailureAnalyzer()


def test_diagnose_module_not_found(analyzer):
    result = {"stderr": "ModuleNotFoundError: No module named 'pandas'", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "ENVIRONMENT"
    assert d.subcategory == "missing_dependency"
    assert "pandas" in d.detail
    assert d.confidence >= 0.9
    assert "manifest.json" in d.target_files


def test_diagnose_import_error(analyzer):
    result = {"stderr": "ImportError: cannot import name 'foo' from 'bar'", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "CODE_ERROR"
    assert d.subcategory == "import_error"


def test_diagnose_syntax_error(analyzer):
    result = {"stderr": "SyntaxError: invalid syntax (run.py, line 10)", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "CODE_ERROR"
    assert d.subcategory == "syntax_error"
    assert "tools/run.py" in d.target_files
    assert d.confidence >= 0.9


def test_diagnose_type_error(analyzer):
    result = {"stderr": "TypeError: unsupported operand type(s)", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "CODE_ERROR"
    assert d.subcategory == "type_error"


def test_diagnose_timeout(analyzer):
    result = {"stderr": "Timeout (30s superato)", "exit_code": -1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "ENVIRONMENT"
    assert d.subcategory == "timeout"
    assert "manifest.json" in d.target_files


def test_diagnose_memory(analyzer):
    result = {"stderr": "MemoryError", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "ENVIRONMENT"
    assert d.subcategory == "memory_limit"


def test_diagnose_name_error(analyzer):
    result = {"stderr": "NameError: name 'undefined_var' is not defined", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "CODE_ERROR"
    assert d.subcategory == "runtime_exception"


def test_diagnose_unknown_error_low_confidence(analyzer):
    result = {"stderr": "something completely unknown happened", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.confidence < 0.6
    assert d.subcategory == "unknown"


def test_diagnose_key_error(analyzer):
    result = {"stderr": "KeyError: 'missing_key'", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "CODE_ERROR"
    assert d.subcategory == "runtime_exception"
