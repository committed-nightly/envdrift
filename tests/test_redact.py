import hashlib
import itertools
import string

from envdrift.redact import SALT_ENV, Redactor


def test_the_same_value_digests_the_same_way_within_one_redactor():
    r = Redactor.build({})
    assert r.digest("hunter2") == r.digest("hunter2")


def test_different_values_digest_differently():
    r = Redactor.build({})
    assert r.digest("hunter2") != r.digest("hunter3")


def test_two_runs_without_a_salt_do_not_agree():
    # The point of the default: a digest is meaningful inside one report only.
    assert Redactor.build({}).digest("x") != Redactor.build({}).digest("x")


def test_a_supplied_salt_makes_two_runs_agree():
    env = {SALT_ENV: "a-real-secret-from-the-ci-store"}
    assert Redactor.build(env).digest("x") == Redactor.build(env).digest("x")


def test_different_salts_do_not_agree():
    a = Redactor.build({SALT_ENV: "salt-one-which-is-long-enough"})
    b = Redactor.build({SALT_ENV: "salt-two-which-is-long-enough"})
    assert a.digest("x") != b.digest("x")


def test_an_empty_salt_is_an_unset_salt():
    # `ENVDRIFT_REDACT_SALT= envdrift ...` must not key every digest with nothing.
    r = Redactor.build({SALT_ENV: ""})
    assert not r.from_env
    assert r.digest("x") != Redactor.build({SALT_ENV: ""}).digest("x")


def test_the_digest_is_not_a_bare_sha256_of_the_value():
    # The exact failure Jen found: the old digest was sha256(value)[:8], so
    # anyone holding the output could sweep a small keyspace and read it back.
    r = Redactor.build({})
    assert r.digest("300") != hashlib.sha256(b"300").hexdigest()[:8]


def test_a_short_value_survives_an_exhaustive_sweep():
    """The whole point, stated as a test.

    `s3cr` came back from the old digest in 0.79s over 36^4. Sweep the same
    keyspace against the new one and nothing should match, because the sweeper
    does not have the salt.
    """
    r = Redactor.build({})
    target = r.digest("s3cr")
    alphabet = string.ascii_lowercase + string.digits
    attacker = hashlib.sha256  # what a cracker would reach for
    for tup in itertools.product(alphabet, repeat=4):
        guess = "".join(tup)
        assert attacker(guess.encode()).hexdigest()[:8] != target
    # And the value really is in the keyspace that was just swept, so the
    # sweep failing means the digest is keyed and not that the test is vacuous.
    assert r.digest("s3cr") == target
    assert all(c in alphabet for c in "s3cr")


def test_the_salt_is_not_in_the_repr():
    salt = "sentinel-salt-value-not-for-printing"
    r = Redactor.build({SALT_ENV: salt})
    assert salt not in repr(r)
    assert "hidden" in repr(r)
    assert SALT_ENV in repr(r)


def test_a_random_redactor_says_so_in_its_repr():
    assert "random" in repr(Redactor.build({}))


def test_a_short_supplied_salt_is_flagged_as_weak():
    assert Redactor.build({SALT_ENV: "abc"}).weak_salt


def test_a_long_supplied_salt_is_not_flagged():
    assert not Redactor.build({SALT_ENV: "x" * 32}).weak_salt


def test_a_random_salt_is_never_weak():
    assert not Redactor.build({}).weak_salt


def test_explain_names_the_env_var_either_way():
    # A reader comparing two reports needs to know which mode produced them.
    assert any(SALT_ENV in line for line in Redactor.build({}).explain())
    assert any(SALT_ENV in line for line in Redactor.build({SALT_ENV: "x" * 32}).explain())


def test_explain_mentions_a_weak_salt():
    text = " ".join(Redactor.build({SALT_ENV: "abc"}).explain())
    assert "guess" in text


def test_values_that_are_not_valid_utf8_still_digest():
    # engines.py reads with surrogateescape, so an outcome can carry lone
    # surrogates. Redaction must not be the thing that crashes on them.
    r = Redactor.build({})
    assert len(r.digest("caf\udcff")) == 8
