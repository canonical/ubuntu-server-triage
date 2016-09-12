#!/usr/bin/env python
"""
Output Ubuntu Server LaunchPad bugs that for triage. Script accepts either
a single date or inclusive range to find bugs.

Copyright 2016 Canonical Ltd.
Joshua Powers <josh.powers@canonical.com>
"""
import argparse
import collections
from datetime import datetime, timedelta
import getpass
from launchpadlib.launchpad import Launchpad
import logging
import os
import sys


LOG_LEVEL = logging.INFO


def connect_launchpad():
    """
    Using the launchpad module connect to launchpad.

    Will connect you to the LaunchPad website the first time you run
    this to autorize your system to connect.
    """
    username = getpass.getuser()
    cachedir = os.path.join('/home', username, '.launchpadlib/cache/')
    # Fails with Python3 due to lp# 1583741
    return Launchpad.login_with(username, 'production', cachedir)


def print_bugs(bugs):
    """
    Prints the bugs in a clean-ish format.
    """
    for bug in sorted(bugs, key=lambda bug: bug.date):
        logging.info('[%s] %-39s - %s' % (bug.date, bug.link, bug.title))


def check_dates(start, end):
    """
    Validate dates are setup correctly so we can print the range
    and then be inclusive in dates.
    """
    # If end date is not set set it to start so we can
    # properly show the inclusive list of dates.
    if not end:
        end = start

    logging.info('%s to %s (inclusive)' % (start, end))

    # If the days are equal, add one to end otherwise this will
    # return an empty list.
    if start == end:
        logging.debug('Adding one day to end date')
        end = datetime.strptime(start, '%Y-%m-%d') + timedelta(days=1)
        end = end.strftime('%Y-%m-%d')

    return start, end


def detailed_bugs(bugs_start, bugs_end):
    """
    Collects the specific information from each bug, versus just the id.

    Returns a named tuple of the last modified date, weblink, and title.
    """
    logging.info('Getting detailed bug information')
    logging.info('Please be paitent, this can take a few minutes...')
    logging.info('---')

    bug_list = []
    Bug = collections.namedtuple('Bug', 'date link title')
    for bug in filter(lambda x: x not in bugs_end, bugs_start):
        bug_list.append(Bug(date=str(bug.bug.date_last_updated)[:19],
                            link=bug.bug.web_link,
                            title=bug.bug.title))

    return bug_list


def find_bugs(launchpad, start, end):
    """
    Subtracts all bugs modified after specified start and end dates.

    This provides the list of bugs between two dates as LaunchPad does
    not appear to have a specific function for searching for a range.
    """
    start, end = check_dates(start, end)

    # Distribution List: https://launchpad.net/distros
    # API Doc: https://launchpad.net/+apidoc/1.0.html
    project = launchpad.distributions['Ubuntu']
    team = launchpad.people['ubuntu-server']

    bugs_start = project.searchTasks(modified_since=start,
                                     structural_subscriber=team)
    logging.debug('Start date bug count: %s', len(bugs_start))

    bugs_end = project.searchTasks(modified_since=end,
                                   structural_subscriber=team)
    logging.debug('End date bug count: %s', len(bugs_end))

    logging.info('Found %i bugs' % (len(bugs_start) - len(bugs_end)))

    return detailed_bugs(bugs_start, bugs_end)


def main(start, end=None):
    """
    Connect to LaunchPad, get range of bugs, print 'em.
    """
    logging.basicConfig(stream=sys.stdout, format='%(message)s',
                        level=LOG_LEVEL)

    logging.info('Ubuntu Server Bug List')
    launchpad = connect_launchpad()
    bugs = find_bugs(launchpad, start, end)
    print_bugs(bugs)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('start_date',
                        help='date to start finding bugs ' +
                             '(e.g. 2016-07-15)')
    parser.add_argument('end_date',
                        nargs='?',
                        help='date to end finding bugs (inclusive) ' +
                             '(e.g. 2016-07-31)')

    args = parser.parse_args()
    main(args.start_date, args.end_date)
