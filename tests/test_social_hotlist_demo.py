from app.social_hotlist import profile


def test_screenshot_demo_is_independent_between_reads():
    first = profile('weibo')
    first['items'][0]['title'] = 'changed'
    assert profile('weibo')['items'][0]['title'] == 'A股'


def test_screenshot_demo_keeps_truncation_and_visible_labels():
    assert profile('douyin')['items'][1]['title'].endswith('…')
    assert profile('weibo')['items'][12]['sentiment'] == '正'
    assert profile('baidu')['items'][0]['sentiment'] == '正'
