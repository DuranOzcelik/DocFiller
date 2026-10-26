"""Offline user accounts — several people sharing one computer.

Each person keeps their own history, record library, field memory and drafts;
none of it is shared with anyone else using the same machine, and none of it
leaves the computer.

Design:

* Accounts are listed in one JSON file in the shared data folder.
* Every account has its own folder, ``<data>/accounts/<id>/``. Once signed in,
  everything the program writes goes there (see ``paths.set_active_root``).
* A password is **optional** and guards against mistakes, not against
  determined access: a local file that anyone at this computer can open cannot
  be protected by a password the program checks. So the password itself is
  never stored — only a salted PBKDF2-SHA256 hash — and the interface describes
  it honestly as "stops someone else working under your name".
* **Profile values** are personal details that belong in documents — a person's
  name, title, licence or registration number. They are entered once and fill
  the matching placeholders in every job automatically.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from . import paths

FILE_NAME = "accounts.json"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# Slow enough for an attacker, instant for a sign-in.
_PBKDF2_ROUNDS = 120_000


@dataclass
class Account:
    id: str
    name: str
    role: str = ""  # shown under the name in the sidebar, e.g. a job title
    profile_values: dict[str, str] = field(default_factory=dict)
    password_hash: str = ""
    salt: str = ""
    created: str = ""
    last_sign_in: str = ""

    @property
    def has_password(self) -> bool:
        return bool(self.password_hash)

    def folder(self) -> Path:
        path = paths.accounts_root() / self.id
        path.mkdir(parents=True, exist_ok=True)
        return path


# --------------------------------------------------------------------- store


def _store_path() -> Path:
    return paths.shared_data_root() / FILE_NAME


def _load() -> dict:
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"accounts": []}
    if not isinstance(data, dict):
        return {"accounts": []}
    data.setdefault("accounts", [])
    return data


def _save(data: dict) -> None:
    paths.atomic_write(_store_path(), json.dumps(data, ensure_ascii=False, indent=2))


# ------------------------------------------------------------------- helpers


def slugify(name: str) -> str:
    """A safe folder name for a display name in any Latin-based script."""
    folded = name.replace("ı", "i").replace("İ", "I").replace("ß", "ss")
    decomposed = unicodedata.normalize("NFKD", folded)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    slug = re.sub(r"[^A-Za-z0-9]+", "-", plain).strip("-").lower()
    return slug or "user"


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ROUNDS
    ).hex()


def initials(name: str) -> str:
    """Two letters for the account badge ('Alex Morgan' -> 'AM')."""
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


# ---------------------------------------------------------------------- CRUD


def _from_dict(entry: dict) -> Account | None:
    if not (isinstance(entry, dict) and entry.get("id") and entry.get("name")):
        return None
    known = {name: entry.get(name) for name in Account.__dataclass_fields__ if name in entry}
    values = known.get("profile_values")
    known["profile_values"] = {str(k): str(v) for k, v in values.items()} if isinstance(values, dict) else {}
    for text_field in ("role", "password_hash", "salt", "created", "last_sign_in"):
        known[text_field] = str(known.get(text_field) or "")
    return Account(**known)


def list_all() -> list[Account]:
    accounts = [a for a in (_from_dict(e) for e in _load()["accounts"]) if a is not None]
    accounts.sort(key=lambda a: a.name.casefold())
    return accounts


def find(account_id: str | None) -> Account | None:
    if not account_id:
        return None
    return next((a for a in list_all() if a.id == account_id), None)


def create(name: str, password: str = "", role: str = "", profile_values: dict | None = None) -> Account:
    """Create an account. A name already in use gets a numeric suffix on its id."""
    name = (name or "").strip()
    if not name:
        raise ValueError("The account name cannot be empty.")
    data = _load()
    taken = {e.get("id") for e in data["accounts"] if isinstance(e, dict)}
    base = slugify(name)
    account_id, suffix = base, 2
    while account_id in taken:
        account_id = f"{base}-{suffix}"
        suffix += 1

    salt = secrets.token_hex(16)
    account = Account(
        id=account_id,
        name=name,
        role=(role or "").strip(),
        profile_values=dict(profile_values or {}),
        password_hash=_hash(password, salt) if password else "",
        salt=salt,
        created=datetime.now().strftime(TIME_FORMAT),
    )
    data["accounts"].append(asdict(account))
    _save(data)
    account.folder()
    return account


def update(account: Account) -> None:
    data = _load()
    for index, entry in enumerate(data["accounts"]):
        if isinstance(entry, dict) and entry.get("id") == account.id:
            data["accounts"][index] = asdict(account)
            _save(data)
            return


def password_matches(account: Account, password: str) -> bool:
    if not account.has_password:
        return True
    if not password:
        return False
    return secrets.compare_digest(_hash(password, account.salt), account.password_hash)


def change_password(account: Account, new_password: str) -> None:
    account.salt = secrets.token_hex(16)
    account.password_hash = _hash(new_password, account.salt) if new_password else ""
    update(account)


def remove(account_id: str) -> bool:
    """Remove the account from the list. ITS FOLDER IS KEPT, so the person's
    history and library survive if the account is created again."""
    data = _load()
    before = len(data["accounts"])
    data["accounts"] = [
        e for e in data["accounts"] if not (isinstance(e, dict) and e.get("id") == account_id)
    ]
    if len(data["accounts"]) == before:
        return False
    _save(data)
    return True


def setup_needed() -> bool:
    return not list_all()


# ------------------------------------------------------------------- session

_active: Account | None = None


def active() -> Account | None:
    return _active


def sign_in(account: Account) -> None:
    """Open the session; everything written from now on goes to this account."""
    global _active
    _active = account
    account.last_sign_in = datetime.now().strftime(TIME_FORMAT)
    update(account)
    paths.set_active_root(account.folder())


def sign_out() -> None:
    global _active
    _active = None
    paths.set_active_root(None)
