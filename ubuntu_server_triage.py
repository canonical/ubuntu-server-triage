#!/usr/bin/env python
"""
Output Ubuntu Server Launchpad bugs that for triage. Script accepts either
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

    Will connect you to the Launchpad website the first time you run
    this to autorize your system to connect.
    """
    username = getpass.getuser()
    cachedir = os.path.join('/home', username, '.launchpadlib/cache/')
    # Fails with Python3 due to lp# 1583741
    return Launchpad.login_with(username, 'production', cachedir)


def check_dates(start, end=None):
    """
    Validate dates are setup correctly so we can print the range
    and then be inclusive in dates.
    """
    # If end date is not set set it to start so we can
    # properly show the inclusive list of dates.
    if not end:
        end = start

    logging.info('%s to %s (inclusive)', start, end)

    # Always add one to end date to make the dates inclusive
    end = datetime.strptime(end, '%Y-%m-%d') + timedelta(days=1)
    end = end.strftime('%Y-%m-%d')

    logging.debug('Searching for %s and %s', start, end)

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
    bug_list = []
    for bug in bugs:
        num = bug.split(' ')[1].replace('#', '')
        src = bug.split(' ')[3]
        title = ' '.join(bug.split(' ')[5:]).replace('"', '')
        bug_list.append((num, src, title))

    bug_list.sort(key=lambda tup: tup[0])

    return bug_list


def modified_bugs(date):
    """
    Returns a list of bugs modified after a specific date.
    """
    # Distribution List: https://launchpad.net/distros
    # API Doc: https://launchpad.net/+apidoc/1.0.html
    launchpad = connect_launchpad()
    project = launchpad.distributions['Ubuntu']
    team = launchpad.people['ubuntu-server']

    # modified and structural_subscriber sans already subscribed by lpname
    mod_bugs = project.searchTasks(modified_since=date,
                                   structural_subscriber=team)
    already_sub_bugs = project.searchTasks(modified_since=date,
                                           structural_subscriber=team,
                                           bug_subscriber=team)
    raw_bugs = [b for b in mod_bugs if b not in already_sub_bugs]

    bugs = [bug.title for bug in raw_bugs]
    logging.debug('Bug count for %s: %s', date, len(bugs))

    return bugs


def create_bug_list(start_date, end_date):
    """
    Subtracts all bugs modified after specified start and end dates.

    This provides the list of bugs between two dates as Launchpad does
    not appear to have a specific function for searching for a range.
    """
    logging.info('Please be paitent, this can take a few minutes...')
    start_date, end_date = check_dates(start_date, end_date)

    start_bugs = modified_bugs(start_date)
    end_bugs = modified_bugs(end_date)

    bugs = [x for x in start_bugs if x not in end_bugs]
    bug_list = bug_info(bugs)

    logging.info('Found %s bugs', len(bug_list))
    logging.info('---')

    return bug_list


def main(start, end=None):
    """
    Connect to Launchpad, get range of bugs, print 'em.
    """
    logging.basicConfig(stream=sys.stdout, format='%(message)s',
                        level=LOG_LEVEL)

    connect_launchpad()
    logging.info('Ubuntu Server Bug List')
    bugs = create_bug_list(start, end)
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
