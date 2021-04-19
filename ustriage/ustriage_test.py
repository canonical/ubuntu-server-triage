"""Test ustriage with pytest."""
import datetime

import pytest

import ustriage.ustriage as target


def parse_test_date(date_string):
    """Parse test date."""
    return datetime.datetime.strptime(date_string, '%Y-%m-%d').date()


@pytest.mark.parametrize('today,keyword,start,end', [
    ('2019-05-14', 'mon', '2019-05-10', '2019-05-12'),
    ('2019-05-14', 'tue', '2019-05-13', '2019-05-13'),
    ('2019-05-13', 'tue', '2019-05-06', '2019-05-06'),
    ('2019-05-14', 'wed', '2019-05-07', '2019-05-07'),
])
def test_auto_date_range(today, keyword, start, end):
    """Test date range."""
    today = parse_test_date(today)
    assert target.auto_date_range(keyword, today=today) == (
        parse_test_date(start), parse_test_date(end)
    )


@pytest.mark.parametrize('today,keyword', [
    ('2019-05-14', 'sun'),
    ('2019-05-14', 'sat'),
])
def test_auto_date_range_weekend(today, keyword):
    """Test weekend date range."""
    today = parse_test_date(today)
    with pytest.raises(ValueError):
        target.auto_date_range(keyword, today=today)


@pytest.mark.parametrize('start,end,expected', [
    ('2019-05-10', '2019-05-12', 'Monday triage'),
    ('2019-05-13', '2019-05-13', 'Tuesday triage'),
    ('2019-05-06', '2019-05-06', 'Tuesday triage'),
    ('2019-05-07', '2019-05-07', 'Wednesday triage'),
    ('2019-05-06', '2019-05-07', None),  # two days apart, not Fri-Sun
    ('2019-05-07', '2019-05-06', None),  # reverse range definition
    ('2019-05-06', '2019-05-09', None),  # more than two days apart
    ('2019-05-18', '2019-05-18', None),  # Saturday
    ('2021-04-16', '2021-04-16', None),  # Friday
])
def test_reverse_auto_date_range(start, end, expected):
    """Test reverse date range."""
    assert target.reverse_auto_date_range(
        parse_test_date(start), parse_test_date(end)
    ) == expected
