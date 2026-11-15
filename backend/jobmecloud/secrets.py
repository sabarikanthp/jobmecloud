"""API keys live in SSM Parameter Store as SecureStrings (standard tier is free)."""

import boto3

PREFIX = "/jobmecloud/"


def _client():
    return boto3.client("ssm")


def _path(name: str) -> str:
    return PREFIX + name.replace(":", "/")


def set_secret(name: str, value: str) -> None:
    _client().put_parameter(Name=_path(name), Value=value.strip(), Type="SecureString",
                            Tier="Standard", Overwrite=True)


def get_secret(name: str) -> str | None:
    ssm = _client()
    try:
        return ssm.get_parameter(Name=_path(name), WithDecryption=True)["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        return None


def delete_secret(name: str) -> None:
    ssm = _client()
    try:
        ssm.delete_parameter(Name=_path(name))
    except ssm.exceptions.ParameterNotFound:
        pass
