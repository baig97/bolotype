from bolotype.editor import match_command, PolishCommand, PolishTarget


def polish(target):
    return ("polish", PolishCommand(target))


def test_polish_line():
    assert match_command("polish this line") == polish(PolishTarget.LINE)

def test_polish_paragraph():
    assert match_command("polish this paragraph") == polish(PolishTarget.PARAGRAPH)

def test_polish_everything():
    assert match_command("polish everything") == polish(PolishTarget.ALL)

def test_polish_all():
    assert match_command("polish all") == polish(PolishTarget.ALL)

def test_polish_selection():
    assert match_command("polish the selection") == polish(PolishTarget.SELECTION)

def test_polish_this_is_all():
    assert match_command("polish this") == polish(PolishTarget.ALL)

def test_undo():
    assert match_command("undo that") == ("undo", ())

def test_undo_it():
    assert match_command("undo it") == ("undo", ())

def test_trailing_punctuation_ignored():
    assert match_command("polish this paragraph.") == polish(PolishTarget.PARAGRAPH)

def test_please_prefix():
    assert match_command("please polish this paragraph") == polish(PolishTarget.PARAGRAPH)

def test_can_you_prefix():
    assert match_command("can you polish everything") == polish(PolishTarget.ALL)

def test_okay_prefix():
    assert match_command("okay polish the selection") == polish(PolishTarget.SELECTION)

def test_trailing_please():
    assert match_command("polish the line please") == polish(PolishTarget.LINE)

def test_both_ends_filler():
    assert match_command("okay polish this paragraph please") == polish(PolishTarget.PARAGRAPH)

def test_missing_determiner():
    assert match_command("polish paragraph") == polish(PolishTarget.PARAGRAPH)

def test_my_determiner():
    assert match_command("polish my paragraph") == polish(PolishTarget.PARAGRAPH)

def test_embedded_command_does_not_fire():
    assert match_command("so then i polish this paragraph until it shines") is None

def test_plain_text_is_not_a_command():
    assert match_command("the weather is nice today") is None

def test_bare_polish_does_not_fire():
    assert match_command("polish") is None

def test_prefix_required_when_set():
    assert match_command("polish everything", command_prefix="computer") is None

def test_prefix_matches():
    assert match_command("computer polish everything", command_prefix="computer") == polish(PolishTarget.ALL)

def test_prefix_with_filler():
    assert match_command("computer please polish paragraph", command_prefix="computer") == polish(PolishTarget.PARAGRAPH)