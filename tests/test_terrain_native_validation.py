"""Native outer semantic checks are controlled data validation only."""

import hashlib

import pytest

from app.simulation.openttd.terrain_native_validation import validate_observations


def test_missing_observations_rejects():
    with pytest.raises(ValueError, match="Missing native observations"):
        validate_observations({}, {}, {}, None)


def test_contract_argv_example():
    from app.simulation.openttd.terrain_native_validation import argv_digest

    argv = [
        "/controlled/openttd",
        "-D127.0.0.1:3979",
        "-c",
        "/controlled/runtime/openttd.cfg",
        "-x",
        "-X",
        "-g",
        "-G",
        "42",
        "-dscript=4,grf=1,net=3",
    ]
    assert argv_digest(argv) == "fd101e0eeb98e6b8b0eea7aceee4735a664873763da2ca115a40a4b247d88c5d"
    argv[-1], argv[-2] = argv[-2], argv[-1]
    assert argv_digest(argv) != "fd101e0eeb98e6b8b0eea7aceee4735a664873763da2ca115a40a4b247d88c5d"


@pytest.mark.parametrize("argument", ["", "e\u0301", "bad\0argument"])
def test_invalid_launch_arguments_rejected(argument):
    from app.simulation.openttd.terrain_native_validation import argv_digest

    with pytest.raises(ValueError, match="Invalid native launch arguments"):
        argv_digest([argument])


def test_binding_identity_uses_exact_canonical_contract_bytes():
    from app.simulation.openttd.terrain_native_validation import binding_identity

    expected = hashlib.sha256(
        b'{"domain":"owned-path","locator":"/controlled/runtime/.admin-secret",'
        b'"policy":"terrain-native-binding-v1"}'
    ).hexdigest()
    assert (
        binding_identity("owned-path", "/controlled/runtime/.admin-secret") == "binding-" + expected
    )
