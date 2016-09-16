#!/usr/bin/env python
"""
Output Ubuntu Server LaunchPad bugs that for triage. Script accepts either
a single date or inclusive range to find bugs.

Copyright 2016 Canonical Ltd.
Joshua Powers <josh.powers@canonical.com>
"""
import argparse
from datetime import datetime, timedelta
import getpass
import logging
import os
import sys


from launchpadlib.launchpad import Launchpad


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


def check_dates(start, end):
    """
    Validate dates are setup correctly so we can print the range
    and then be inclusive in dates.
    """
    # If end date is not set set it to start so we can
    # properly show the inclusive list of dates.
    if not end:
        end = start

    logging.info('%s to %s (inclusive)', start, end)

    # If the days are equal, add one to end otherwise this will
    # return an empty list.
    if start == end:
        logging.debug('Adding one day to end date')
        end = datetime.strptime(start, '%Y-%m-%d') + timedelta(days=1)
        end = end.strftime('%Y-%m-%d')

    return start, end


def print_bugs(bugs):
    """
    Prints the bugs in a clean-ish format.
    """
    for bug in bugs:
        bug_url = 'https://bugs.launchpad.net/bugs/'
        logging.info('%s%-7s - [%s] %s', bug_url, bug[0], bug[1], bug[2])


def bug_info(bugs):
    """
    Collects the specific information for each bug entry.

    If detailed information is specified, than additional data is pulled
    in by the script, like last_updated, web link, title. This however
    takes a considerable amount of time.
    """
    logging.debug('Getting bug information')
    bug_list = []
    for bug in bugs:
        num = bug.title.split(' ')[1].replace('#', '')
        src = bug.title.split(' ')[3]
        title = ' '.join(bug.title.split(' ')[5:]).replace('"', '')
        bug_list.append((num, src, title))

    bug_list.sort(key=lambda tup: tup[0])

    return bug_list


def find_bugs(launchpad, start, end):
    """
    Subtracts all bugs modified after specified start and end dates.

    This provides the list of bugs between two dates as LaunchPad does
    not appear to have a specific function for searching for a range.
    """
    # Distribution List: https://launchpad.net/distros
    # API Doc: https://launchpad.net/+apidoc/1.0.html
    project = launchpad.distributions['Ubuntu']
    team = launchpad.people['ubuntu-server']

    start, end = check_dates(start, end)

    logging.info('Please be paitent, this can take a few minutes...')
    bugs_start = project.searchTasks(modified_since=start,
                                     structural_subscriber=team)
    logging.debug('Start date bug count: %s', len(bugs_start))

    bugs_end = project.searchTasks(modified_since=end,
                                   structural_subscriber=team)
    logging.debug('End date bug count: %s', len(bugs_end))

    bugs_start = set(bugs_start)
    bugs = [x for x in bugs_start if x not in bugs_end]

    bug_list = bug_info(bugs)
    logging.info('Found %s bugs', len(bug_list))
    logging.info('---')

    return bug_list


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
    PARSER = argparse.ArgumentParser()
    PARSER.add_argument('start_date',
                        help='date to start finding bugs ' +
                        '(e.g. 2016-07-15)')
    PARSER.add_argument('end_date',
                        nargs='?',
                        help='date to end finding bugs (inclusive) ' +
                        '(e.g. 2016-07-31)')
    PARSER.add_argument('-d', '--debug', action='store_true',
                        help='debug output')

    ARGS = PARSER.parse_args()

    if ARGS.debug:
        LOG_LEVEL = logging.DEBUG

    main(ARGS.start_date, ARGS.end_date)
