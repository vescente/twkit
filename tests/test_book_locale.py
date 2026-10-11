from twkit import book as BK


def test_new_workbook_opens_with_irish_locale():
    assert BK.skeleton().get("locale") == "en_IE"
    assert BK.Book().root.get("locale") == "en_IE"


def test_locale_written_first_like_desktop():
    assert list(BK.skeleton().attrib)[0] == "locale"
