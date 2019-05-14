import datetime

import pytest

import ustriage.ustriage as target


def parse_test_date(date_string):
    return datetime.datetime.strptime(date_string, '%Y-%m-%d').date()


@pytest.mark.parametrize('today,keyword,start,end', [
    ('2019-05-14', 'mon', '2019-05-10', '2019-05-12'),
    ('2019-05-14', 'tue', '2019-05-13', '2019-05-13'),
    ('2019-05-13', 'tue', '2019-05-06', '2019-05-06'),
    ('2019-05-14', 'wed', '2019-05-07', '2019-05-07'),
])
def test_auto_date_range(today, keyword, start, end):
    today = parse_test_date(today)
    assert target.auto_date_range(keyword, today=today) == (parse_test_date(start), parse_test_date(end))


@pytest.mark.parametrize('today,keyword', [
    ('2019-05-14', 'sun'),
    ('2019-05-14', 'sat'),
])
def test_auto_date_range_weekend(today, keyword):
    today = parse_test_date(today)
    with pytest.raises(ValueError):
        target.auto_date_range(keyword, today=today)
