from envdrift import hazards
from envdrift.engines import BY_NAME


def test_finds_command_substitution_with_its_line():
    (hazard,) = hazards.scan("A=1\nB=$(id)\n")
    assert hazard.line_no == 2
    assert hazard.construct == "$("
    assert "command substitution" in hazard.description


def test_finds_backticks():
    (hazard,) = hazards.scan("A=`id`\n")
    assert hazard.construct == "`"


def test_one_line_can_hold_two_constructs():
    found = hazards.scan("A=$(id)`id`\n")
    assert sorted(h.construct for h in found) == ["$(", "`"]


def test_whole_line_comments_are_ignored():
    assert hazards.scan("# $(id) and `id`\nA=1\n") == []
    assert hazards.scan("   # $(id)\n") == []


def test_a_trailing_comment_is_not_ignored():
    # Whether the `#` starts a comment is itself something the parsers disagree
    # about, so a `$(` after one still counts.
    assert len(hazards.scan("A=1 # $(id)\n")) == 1


def test_quoted_constructs_still_count():
    # Deliberate: deciding that a quote makes `$(` inert means picking one
    # parser's rules, which is the question the whole tool is asking.
    assert len(hazards.scan("A='$(id)'\n")) == 1


def test_bash_is_held_back_by_either_construct():
    bash = BY_NAME["bash"]
    assert hazards.held_back_reason(bash, hazards.scan("A=`id`\n")) is not None
    assert hazards.held_back_reason(bash, hazards.scan("A=$(id)\n")) is not None


def test_ruby_is_held_back_by_substitution_but_not_backticks():
    # Dotenv.parse runs $(...) and leaves backticks alone -- verified against
    # the gem in test_engines.py.
    ruby = BY_NAME["ruby-dotenv"]
    assert hazards.held_back_reason(ruby, hazards.scan("A=$(id)\n")) is not None
    assert hazards.held_back_reason(ruby, hazards.scan("A=`id`\n")) is None


def test_a_parser_that_executes_nothing_is_never_held_back():
    node = BY_NAME["node"]
    assert node.executes == ()
    assert hazards.held_back_reason(node, hazards.scan("A=$(id)`id`\n")) is None


def test_reason_names_the_lines_and_caps_the_list():
    body = "".join(f"K{i}=$(id)\n" for i in range(9))
    reason = hazards.held_back_reason(BY_NAME["bash"], hazards.scan(body))
    assert "line 1" in reason and "+5 more" in reason
    assert "--unsafe" in reason
