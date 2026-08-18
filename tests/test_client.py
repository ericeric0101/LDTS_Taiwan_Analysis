from ldts.scraper.client import Client


def test_postback_data_serializes_successful_form_controls():
    html = """
    <form>
      <input type="hidden" name="__VIEWSTATE" value="state">
      <input type="text" name="facility" value="醫院">
      <input type="checkbox" name="checked" value="yes" checked>
      <input type="checkbox" name="unchecked" value="no">
      <select name="city"><option value="">全部</option><option value="臺北市" selected>臺北市</option></select>
      <input type="submit" name="submit" value="查詢">
    </form>
    """
    data = Client.postback_data(html, "search", {"facility": "新名稱"})
    assert data == {
        "__VIEWSTATE": "state",
        "facility": "新名稱",
        "checked": "yes",
        "city": "臺北市",
        "__EVENTTARGET": "search",
        "__EVENTARGUMENT": "",
    }
