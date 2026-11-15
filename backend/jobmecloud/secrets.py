import keyring
from keyring.errors import PasswordDeleteError

SERVICE = "jobmecloud"


def set_secret(name: str, value: str) -> None:
    keyring.set_password(SERVICE, name, value.strip())


def get_secret(name: str) -> str | None:
    return keyring.get_password(SERVICE, name)


def delete_secret(name: str) -> None:
    try:
        keyring.delete_password(SERVICE, name)
    except PasswordDeleteError:
        pass
