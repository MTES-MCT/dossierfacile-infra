"""
Utilitaires d'environnement pour la CLI Outscale.
- Chargement optionnel d'un fichier .env
- Résolution d'identifiants et de région depuis les variables d'environnement
- Préparation d'un HOME temporaire pour oapi-cli si nécessaire
"""
from __future__ import annotations

import os
import json
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple

# Tentative d'utilisation de python-dotenv si disponible
try:
    from dotenv import load_dotenv, find_dotenv  # type: ignore
except Exception:  # pragma: no cover - fallback sans dépendance
    load_dotenv = None  # type: ignore
    find_dotenv = None  # type: ignore


def _manual_find_env() -> Optional[Path]:
    """Recherche manuelle d'un fichier .env en partant du CWD, puis du dossier du module,
    puis de la racine du repo (parent de ce module).
    """
    # 1) Depuis le CWD
    try:
        cwd = Path(os.getcwd()).resolve()
        for p in [cwd, *cwd.parents]:
            candidate = p / ".env"
            if candidate.exists():
                return candidate
    except Exception:
        pass
    # 2) Dossier du module
    try:
        module_dir_env = Path(__file__).resolve().parent / ".env"
        if module_dir_env.exists():
            return module_dir_env
    except Exception:
        pass
    # 3) Racine du repo (parent du package outscale)
    try:
        repo_root = Path(__file__).resolve().parents[1]
        candidate = repo_root / ".env"
        if candidate.exists():
            return candidate
    except Exception:
        pass
    return None


def _manual_load_env(path: Path) -> None:
    """Charge un fichier .env de manière simple, sans override.
    Gère les lignes commentées, les quotes et un éventuel préfixe "export ".
    """
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            key = k.strip()
            val = v.strip()
            if key.lower().startswith("export "):
                key = key.split(" ", 1)[1].strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass


def load_dotenv_if_present() -> None:
    """Charge un fichier .env si présent. N'écrase pas les variables existantes.
    Essaie d'abord python-dotenv (si installé), sinon passe par un fallback manuel.
    """
    # Si python-dotenv est disponible
    if load_dotenv and find_dotenv:
        # 1) Cherche depuis le CWD vers le haut
        path = find_dotenv(usecwd=True)  # type: ignore[arg-type]
        if path:
            load_dotenv(path, override=False)  # type: ignore[call-arg]
            return
        # 2) Dans le dossier du module
        module_dir_env = Path(__file__).resolve().parent / ".env"
        if module_dir_env.exists():
            load_dotenv(module_dir_env, override=False)  # type: ignore[call-arg]
            return
        # 3) À la racine du repo
        repo_root = Path(__file__).resolve().parents[1]
        env_path = repo_root / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)  # type: ignore[call-arg]
            return
    # Fallback manuel
    p = _manual_find_env()
    if p is not None:
        _manual_load_env(p)


# -------- Résolution des variables d'environnement --------

def pick_first_env(*names: str) -> Optional[str]:
    """Renvoie la première variable d'env définie parmi `names` (ou None)."""
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def resolve_oapi_credentials(
    cli_access_key: Optional[str], cli_secret_key: Optional[str], cli_region: Optional[str]
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Résout identifiants/région pour oapi-cli.
    Priorité:
      1) Options CLI (--access-key/--secret-key/--region)
      2) OUTSCALE_* (avec prise en charge de OUTSCALE_ACCESSS_KEY typo)
      3) OSC_* ou AWS_*
    """
    ak = cli_access_key or pick_first_env(
        "OUTSCALE_ACCESSS_KEY",  # typo courante
        "OUTSCALE_ACCESS_KEY",
        "OSC_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
    )
    sk = cli_secret_key or pick_first_env(
        "OUTSCALE_SECRET_KEY",
        "OSC_SECRET_KEY",
        "AWS_SECRET_ACCESS_KEY",
    )
    rg = cli_region or pick_first_env("OUTSCALE_REGION", "OSC_REGION", "AWS_REGION")
    return ak, sk, rg


def build_oapi_env(
    base_env: Dict[str, str], access_key: Optional[str], secret_key: Optional[str], region: Optional[str]
) -> Dict[str, str]:
    env = dict(base_env)
    if access_key:
        env["OSC_ACCESS_KEY"] = access_key
    if secret_key:
        env["OSC_SECRET_KEY"] = secret_key
    if region:
        env["OSC_REGION"] = region
    return env


def maybe_prepare_oapi_config(
    env: Dict[str, str], access_key: Optional[str], secret_key: Optional[str], region: Optional[str]
) -> Dict[str, str]:
    """Crée un HOME temporaire avec ~/.osc/config.json si absent et si AK/SK fournis.
    Évite l'erreur de lecture de config sur certains environnements.
    """
    home = Path(env.get("HOME") or str(Path.home()))
    config_path = home / ".osc" / "config.json"
    if config_path.exists():
        return env
    if not (access_key and secret_key):
        return env

    temp_home = Path(tempfile.mkdtemp(prefix="osc-home-"))
    osc_dir = temp_home / ".osc"
    osc_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "default": {
            "access_key": access_key,
            "secret_key": secret_key,
            "region": region,
        }
    }
    (osc_dir / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    new_env = dict(env)
    new_env["HOME"] = str(temp_home)
    new_env.setdefault("OSC_PROFILE", "default")
    return new_env

