"""Tests for the injectable MAXX EUC transformer."""

import json

import pytest

from app.schemas.migration import CodeAnalysis, EucMetadata
from app.services.migration.transformer import (
    TransformationError,
    transform,
)


class FakeProvider:
    """Deterministic provider that records the transformation prompt."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


@pytest.fixture
def metadata() -> EucMetadata:
    return EucMetadata(
        name="cmfst-global-limit",
        description="Example migration",
        owner_team="Example Team",
        support_team="Example Support",
        secret_references=[
            {"name": "client_id", "vault": "example-vault", "key": "client-id"},
            {
                "name": "client_secret",
                "vault": "example-vault",
                "key": "client-secret",
            },
        ],
        dependencies=["requests"],
    )


@pytest.fixture
def analysis() -> CodeAnalysis:
    return CodeAnalysis(
        imports=["requests", "sglambdautils.lambda_secret.secret"],
        functions=[],
        entrypoint="run",
        maxx_imports=["sglambdautils.lambda_secret.secret"],
        secret_usages=["client_id", "client_secret"],
        external_urls=["https://example.internal/api"],
        warnings=[],
    )


@pytest.fixture
def source_code() -> str:
    return 'def run(json_input):\n    return {"value": json_input}\n'


@pytest.fixture
def specification() -> str:
    return "src/main.py is the standardized entrypoint."


def _response(metadata: EucMetadata) -> str:
    return json.dumps(
        {
            "name": metadata.name,
            "files": [
                {
                    "path": "src/main.py",
                    "content": "from .logic import run\n",
                },
                {
                    "path": "src/logic.py",
                    "content": "def run(json_input):\n    return json_input\n",
                },
                {
                    "path": "config/config.yaml",
                    "content": (
                        "secrets:\n"
                        "  client_id:\n"
                        "    vault: example-vault\n"
                        "    key: client-id\n"
                        "  client_secret:\n"
                        "    vault: example-vault\n"
                        "    key: client-secret\n"
                    ),
                },
                {"path": "requirements.txt", "content": "requests\n"},
                {"path": "README.md", "content": "# cmfst-global-limit\n"},
                {"path": "Dockerfile", "content": "FROM python:3.12-slim\n"},
            ],
            "warnings": ["Email delivery requires runtime configuration."],
            "unsupported_features": ["MAXX context injection"],
        }
    )


def test_successful_transformation_and_provider_invocation(
    source_code: str,
    analysis: CodeAnalysis,
    metadata: EucMetadata,
    specification: str,
) -> None:
    provider = FakeProvider(_response(metadata))

    result = transform(source_code, analysis, metadata, specification, provider)
    contents = "\n".join(generated_file.content for generated_file in result.files)

    assert "get_lambda_secret(" not in contents
    assert "sglambdautils" not in contents
    assert "client-id" in contents
    assert "client-secret" in contents
    assert "actual-secret-value" not in contents

    assert provider.prompts
    assert result.name == metadata.name
    assert len(result.files) == 7
    assert any(generated_file.path == "src/runner.py" for generated_file in result.files)
    dockerfile = next(
        generated_file for generated_file in result.files if generated_file.path == "Dockerfile"
    )
    assert 'ENTRYPOINT ["python", "-m", "src.runner"]' in dockerfile.content


def test_prompt_contains_source_analysis_metadata_and_specification(
    source_code: str,
    analysis: CodeAnalysis,
    metadata: EucMetadata,
    specification: str,
) -> None:
    provider = FakeProvider(_response(metadata))

    transform(source_code, analysis, metadata, specification, provider)

    prompt = provider.prompts[0]
    assert source_code in prompt
    assert "sglambdautils.lambda_secret.secret" in prompt
    assert "client_secret" in prompt
    assert specification in prompt
    assert "Preserve business logic" in prompt
    assert "Never include actual secret values" in prompt
    assert "# No external dependencies required" in prompt
    assert "entire response MUST be ONLY one valid JSON object" in prompt
    assert "Do not include Markdown" in prompt
    assert "Do not omit any of the four top-level fields" in prompt


def test_warnings_and_unsupported_features_are_preserved(
    source_code: str,
    analysis: CodeAnalysis,
    metadata: EucMetadata,
    specification: str,
) -> None:
    provider = FakeProvider(_response(metadata))

    result = transform(source_code, analysis, metadata, specification, provider)

    assert result.warnings == ["Email delivery requires runtime configuration."]
    assert result.unsupported_features == ["MAXX context injection"]


def test_fenced_json_response_is_parsed(
    source_code: str,
    analysis: CodeAnalysis,
    metadata: EucMetadata,
    specification: str,
) -> None:
    provider = FakeProvider(f"```json\n{_response(metadata)}\n```")

    result = transform(source_code, analysis, metadata, specification, provider)

    assert result.files[0].path == "src/main.py"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ("not json", "not valid JSON"),
        (
            (
                '{"name": "cmfst-global-limit", "files": [], '
                '"warnings": [], "unsupported_features": []}'
            ),
            "src/main.py",
        ),
    ],
)
def test_malformed_provider_response_fails_cleanly(
    response: str,
    message: str,
    source_code: str,
    analysis: CodeAnalysis,
    metadata: EucMetadata,
    specification: str,
) -> None:
    with pytest.raises(TransformationError, match=message):
        transform(
            source_code,
            analysis,
            metadata,
            specification,
            FakeProvider(response),
        )


def test_response_missing_generated_euc_fields_fails_cleanly(
    source_code: str,
    analysis: CodeAnalysis,
    metadata: EucMetadata,
    specification: str,
) -> None:
    response = json.dumps(
        {
            "name": metadata.name,
            "files": [{"path": "src/main.py", "content": "def run(value):\n    return value\n"}],
        }
    )

    with pytest.raises(TransformationError, match="does not match GeneratedEUC"):
        transform(
            source_code,
            analysis,
            metadata,
            specification,
            FakeProvider(response),
        )


def test_missing_required_generated_file_fails_cleanly(
    source_code: str,
    analysis: CodeAnalysis,
    metadata: EucMetadata,
    specification: str,
) -> None:
    response = json.dumps(
        {
            "name": metadata.name,
            "files": [{"path": "README.md", "content": "docs"}],
            "warnings": [],
            "unsupported_features": [],
        }
    )

    with pytest.raises(TransformationError, match="src/main.py"):
        transform(
            source_code,
            analysis,
            metadata,
            specification,
            FakeProvider(response),
        )


def test_generated_name_must_match_metadata(
    source_code: str,
    analysis: CodeAnalysis,
    metadata: EucMetadata,
    specification: str,
) -> None:
    generated = json.loads(_response(metadata))
    generated["name"] = "different-euc-name"

    with pytest.raises(
        TransformationError,
        match="Generated EUC name must match the supplied metadata name",
    ):
        transform(
            source_code,
            analysis,
            metadata,
            specification,
            FakeProvider(json.dumps(generated)),
        )


def test_maxx_secret_retrieval_is_rejected_in_generated_code(
    source_code: str,
    analysis: CodeAnalysis,
    metadata: EucMetadata,
    specification: str,
) -> None:
    response = json.dumps(
        {
            "name": metadata.name,
            "files": [
                {
                    "path": "src/main.py",
                    "content": 'return get_lambda_secret("client_id")',
                }
            ],
            "warnings": [],
            "unsupported_features": [],
        }
    )

    with pytest.raises(TransformationError, match="get_lambda_secret"):
        transform(
            source_code,
            analysis,
            metadata,
            specification,
            FakeProvider(response),
        )


def test_generated_files_use_safe_secret_references_not_values(
    source_code: str,
    analysis: CodeAnalysis,
    metadata: EucMetadata,
    specification: str,
) -> None:
    provider = FakeProvider(_response(metadata))

    transform(source_code, analysis, metadata, specification, provider)


def test_transform_repairs_overescaped_python_content(
    source_code: str,
    analysis: CodeAnalysis,
    metadata: EucMetadata,
    specification: str,
) -> None:
    response = json.dumps(
        {
            "name": metadata.name,
            "files": [
                {
                    "path": "src/main.py",
                    "content": "def run(input_data, context):\n"
                    "    return {\\\"message\\\": \\\"Hello\\\"}\n",
                }
            ],
            "warnings": [],
            "unsupported_features": [],
        }
    )

    generated = transform(
    source_code,
    analysis,
    metadata,
    specification,
        FakeProvider(response),
    )

    assert generated.files[0].content == (
        "def run(input_data, context):\n"
        '    return {"message": "Hello"}\n'
    )
