import os
import sys


def test_cli_autoloads_dotenv(monkeypatch, tmp_path):
    env_dir = tmp_path
    (env_dir / ".env").write_text("FOO=bar\nENV=testing\n")
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.chdir(env_dir)
    sys.modules.pop("tal.cli", None)

    import tal.cli  # noqa: F401  # pylint: disable=unused-import

    assert os.getenv("FOO") == "bar"
    assert os.getenv("ENV") == "testing"


def test_cli_does_not_override_existing_env(monkeypatch, tmp_path):
    env_dir = tmp_path
    (env_dir / ".env").write_text("WILL_NOT_OVERRIDE=yes\n")
    monkeypatch.setenv("WILL_NOT_OVERRIDE", "no")
    monkeypatch.chdir(env_dir)
    sys.modules.pop("tal.cli", None)

    import tal.cli  # noqa: F401  # pylint: disable=unused-import

    assert os.getenv("WILL_NOT_OVERRIDE") == "no"
