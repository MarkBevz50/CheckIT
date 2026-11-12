"""requirements.txt is complete, fully pinned and free of the old scaffold packages;
the Dockerfile installs only from it."""

import ast
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

# import name -> distribution name, where they differ
DISTRIBUTION = {
    "fitz": "pymupdf",
    "docx": "python-docx",
    "jose": "python-jose",
    "google": "google-generativeai",
    "pydantic_settings": "pydantic-settings",
}
# imported by the code from the standard library of the project itself
LOCAL = {"app", "scraper", "tests"}

OLD_SCAFFOLD = {
    "selenium", "webdriver-manager", "pandas", "flask", "g4f", "pywebview", "pythonnet",
    "beautifulsoup4", "duckduckgo-search", "cairosvg", "browser-cookie3",
}


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned_requirements() -> dict:
    pins = {}
    for line in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, _, version = line.partition("==")
            pins[normalize(name)] = version
    return pins


def test_every_requirement_is_pinned_to_an_exact_version():
    for line in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            assert re.fullmatch(r"[A-Za-z0-9_.\-]+==[^\s=<>~!]+", line), f"not pinned: {line}"


def test_direct_dependencies_are_all_present_in_the_pinned_file():
    pins = pinned_requirements()
    direct = []
    for line in (BACKEND / "requirements.in").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            direct.append(normalize(re.split(r"[\[=<>~! ]", line)[0]))
    assert direct, "requirements.in is empty"
    assert [name for name in direct if name not in pins] == []


def test_old_scaffold_packages_are_gone():
    assert OLD_SCAFFOLD & set(pinned_requirements()) == set()


def test_every_third_party_import_of_the_code_is_in_requirements():
    pins = pinned_requirements()
    missing = set()
    sources = [*(BACKEND / "app").rglob("*.py"), *(BACKEND / "alembic").rglob("*.py")]
    sources += [p for p in (REPO / "scraper").rglob("*.py") if "tests" not in p.parts]
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module.split(".")[0]]
            for module in modules:
                if module in sys.stdlib_module_names or module in LOCAL:
                    continue
                if normalize(DISTRIBUTION.get(module, module)) not in pins:
                    missing.add(module)
    assert missing == set()


def test_dockerfile_installs_python_packages_only_from_requirements_txt():
    installs = [
        line.strip()
        for line in (BACKEND / "Dockerfile").read_text(encoding="utf-8").splitlines()
        if "pip install" in line
    ]
    assert installs, "the Dockerfile must install the requirements"
    for line in installs:
        assert "-r /tmp/requirements.txt" in line or "--upgrade pip" in line, line


def test_root_scaffold_files_are_gone():
    for name in ("package.json", "package-lock.json", "babel.config.js", "vue.config.js", "jsconfig.json",
                 "requirements.txt", "host_prozorro.py"):
        assert not (REPO / name).exists(), name
