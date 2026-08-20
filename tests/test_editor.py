from bolotype.editor import match_command, PolishCommand, PolishTarget

#--------- commands that work today ---------

def test_polish_line():
    assert match_command("polish this line") == ("polish", PolishCommand(PolishTarget.LINE))


def test_polish_paragraph():
    assert match_command("polish this paragraph") == ("polish", PolishCommand(PolishTarget.PARAGRAPH))

def test_polish_everything():
    assert match_command("polish everything") == ("polish", PolishCommand(PolishTarget.ALL))

def test_polish_this_is_all():
    assert match_command("polish this") == ("polish", PolishCommand(PolishTarget.ALL))

def test_undo():
    assert match_command("undo that") == ("undo", ())

def test_trailing_punctuation_ignored():
    assert match_command("polish this paragraph.") == ("polish", PolishCommand(PolishTarget.PARAGRAPH))

def test_plain_text_is_not_a_command():
    assert match_command("the weather is nice today") is None


# --- command prefix behaviour ---

def test_prefix_required_when_set():
    # with a prefix configured, a bare command should NOT fire
    assert match_command("polish everything", command_prefix="computer") is None

def test_prefix_matches():
    assert match_command("computer polish everything", command_prefix="computer") == \
        ("polish", PolishCommand(PolishTarget.ALL))


# --- KNOWN GAPS (documenting today's brittleness; these flip in Move 2) ---

def test_filler_prefix_not_recognized_yet():
    assert match_command("please polish this paragraph") is None

def test_missing_determiner_not_recognized_yet():
    assert match_command("polish paragraph") is None