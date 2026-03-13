FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /action

COPY pyproject.toml ./
COPY action ./action

RUN python - <<'PY'
import pathlib
import tomllib

pyproject = tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))
version = pyproject["project"]["version"]
pathlib.Path("/action/action/release_tag.txt").write_text(f"v{version}\n", encoding="utf-8")
PY

RUN python -m py_compile /action/action/entrypoint.py

ENTRYPOINT ["python", "/action/action/entrypoint.py"]
