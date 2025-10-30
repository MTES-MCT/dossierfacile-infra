"""
Service oapi-cli (Outscale API) : exécution du binaire et utilitaires associés.
"""
from __future__ import annotations

from typing import Dict, Tuple, Any, Optional

import subprocess
import json
from pathlib import Path
import click


def run_oapi_cli(oapi_bin: str, args: list[str], env: Dict[str, str]) -> Tuple[int, str, str]:
    """Exécute oapi-cli et renvoie (code, stdout, stderr)."""
    try:
        proc = subprocess.run(
            [oapi_bin] + args, env=env, check=False, capture_output=True, text=True
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError as e:  # pragma: no cover - message CLI
        raise click.ClickException(
            f"Binaire '{oapi_bin}' introuvable. Installez oapi-cli (ex: npm i -g @outscale/oapi-cli) ou fournissez --oapi-bin."
        ) from e


def append_result_json(file_path: Path | str, record: Dict[str, Any]) -> None:
    """Append un record JSON dans un fichier sans l'écraser.
    - Si le fichier n'existe pas: crée un JSON Lines
    - Si c'est un tableau JSON: charge, append, ré-écrit
    - Sinon: JSON Lines
    """
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        return
    try:
        with p.open("r", encoding="utf-8") as f:
            start = f.read(1)
            rest = f.read()
        if start == "[":
            content = start + rest
            try:
                arr = json.loads(content)
                if isinstance(arr, list):
                    arr.append(record)
                    p.write_text(json.dumps(arr, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    return
            except Exception:
                pass
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except FileNotFoundError:
        p.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

