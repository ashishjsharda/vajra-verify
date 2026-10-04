"""Path classification: tests, docs, fixtures, config, CI, lockfiles, areas."""

from __future__ import annotations

import posixpath
import re

TEST_DIR_MARKERS = ("/test/", "/tests/", "/__tests__/", "/spec/")
TEST_SUFFIXES = (
    "_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", "_test.go", "_test.rs",
)

DOC_EXTS = {".md", ".markdown", ".rst", ".adoc", ".txt"}
DOC_STEMS = {"readme", "license", "licence", "copying", "notice", "authors",
             "contributors", "changelog", "changes", "history", "code_of_conduct"}

FIXTURE_MARKERS = ("/fixtures/", "/fixture/", "/testdata/", "/__snapshots__/")

CI_MARKERS = ("/.github/", "/.circleci/", "/.buildkite/", "/.gitlab/")
CI_NAMES = {".gitlab-ci.yml", ".travis.yml", "azure-pipelines.yml", "jenkinsfile",
            "bitbucket-pipelines.yml", ".drone.yml"}

LOCKFILES = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
             "bun.lockb", "poetry.lock", "pipfile.lock", "uv.lock", "pdm.lock",
             "cargo.lock", "go.sum", "gemfile.lock", "composer.lock"}
DEPENDENCY_MANIFESTS = {"package.json", "requirements.txt", "pyproject.toml", "go.mod",
                        "cargo.toml"}

CONFIG_NAMES = {"dockerfile", "makefile", ".gitignore", ".gitattributes", ".editorconfig",
                ".dockerignore", ".npmrc", ".nvmrc", ".python-version", "setup.cfg",
                "tox.ini", "pytest.ini", ".flake8", "mypy.ini", "procfile"}
CONFIG_EXTS = {".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".properties"}
CONFIG_PATTERNS = (
    re.compile(r"^tsconfig.*\.json$"), re.compile(r"^\.eslintrc"), re.compile(r"^\.prettierrc"),
    re.compile(r"^\.babelrc"), re.compile(r"^jest\.config\."), re.compile(r"^vite\.config\."),
    re.compile(r"^\.env"), re.compile(r"^docker-compose"),
)

CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".java",
             ".kt", ".kts", ".rb", ".php", ".cs", ".swift", ".scala", ".c", ".h", ".cc",
             ".cpp", ".hpp", ".m", ".ex", ".exs", ".sh"}
JS_EXTS = {".ts", ".tsx", ".js", ".jsx"}

SENSITIVE_TERMS = ("auth", "payment", "charge", "billing", "permission", "webhook",
                   "migration", "upload", "secret", "session", "password")

ROOT_WORDS = {"src", "app", "lib"}
TEST_WORDS = {"test", "tests", "__tests__", "spec"}


def _slash(path: str) -> str:
    return "/" + path.lstrip("/").lower()


def basename(path: str) -> str:
    return posixpath.basename(path).lower()


def extension(path: str) -> str:
    return posixpath.splitext(basename(path))[1]


def is_test(path: str) -> bool:
    p = _slash(path)
    if any(m in p for m in TEST_DIR_MARKERS):
        return True
    b = basename(path)
    return (b.startswith("test_") and b.endswith(".py")) or b.endswith(TEST_SUFFIXES)


def is_lockfile(path: str) -> bool:
    return basename(path) in LOCKFILES


def is_dependency_file(path: str) -> bool:
    return basename(path) in DEPENDENCY_MANIFESTS or is_lockfile(path)


def is_doc(path: str) -> bool:
    if is_dependency_file(path):
        return False
    p = _slash(path)
    if "/docs/" in p or "/doc/" in p:
        return True
    stem, ext = posixpath.splitext(basename(path))
    return ext in DOC_EXTS or stem in DOC_STEMS


def is_fixture(path: str) -> bool:
    p = _slash(path)
    return any(m in p for m in FIXTURE_MARKERS) or p.endswith(".snap")


def is_ci(path: str) -> bool:
    p = _slash(path)
    return any(m in p for m in CI_MARKERS) or basename(path) in CI_NAMES


def is_config(path: str) -> bool:
    b = basename(path)
    if is_dependency_file(path) or b in CONFIG_NAMES or extension(path) in CONFIG_EXTS:
        return True
    return any(rx.search(b) for rx in CONFIG_PATTERNS)


def is_production(path: str) -> bool:
    return not (is_test(path) or is_doc(path) or is_fixture(path) or is_ci(path)
                or is_config(path) or is_lockfile(path))


def is_code(path: str) -> bool:
    return extension(path) in CODE_EXTS


def is_js_like(path: str) -> bool:
    return extension(path) in JS_EXTS


def sensitive_terms(text: str) -> list[str]:
    low = text.lower()
    return [t for t in SENSITIVE_TERMS if t in low]


def area(path: str) -> tuple[str, ...]:
    """First two meaningful directory components after stripping known roots.

    Empty tuple means the area cannot be determined.
    """
    parts = [p for p in path.split("/")[:-1] if p]
    if len(parts) >= 3 and parts[0] == "packages" and parts[2] in ROOT_WORDS:
        parts = parts[3:]
    meaningful = [p.lower() for p in parts if p.lower() not in ROOT_WORDS | TEST_WORDS]
    return tuple(meaningful[:2])


def areas_related(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    if not a or not b:
        return False
    k = min(len(a), len(b))
    return a[:k] == b[:k]
