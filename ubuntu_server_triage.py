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
import webbrowser

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


def check_dates(start, end=None, nodatefilter=False):
    """
    Validate dates are setup correctly so we can print the range
    and then be inclusive in dates.
    """
    # if start date is not set we search all bugs of a LP user/team
    if not start:
        if nodatefilter:
            logging.info('Searching all bugs, no date filter')
            return datetime.min, datetime.now()
        else:
            logging.info('No date set, auto-search yesterday/weekend for the '
                         'most common triage.')
            logging.info('Please specify -a if you really '
                         'want to search without any date filter')
            yesterday = datetime.now().date() - timedelta(days=1)
            if yesterday.weekday() != 6:
                start = yesterday.strftime('%Y-%m-%d')
            else:
                # include weekend if yesterday was a sunday
                start = (yesterday - timedelta(days=2)).strftime('%Y-%m-%d')
                end = yesterday.strftime('%Y-%m-%d')

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


def print_bugs(bugs, open_in_browser=False, shortlinks=True):
    """
    Prints the bugs in a clean-ish format.
    """
    if shortlinks:
        bug_url = 'LP: #'
    else:
        bug_url = 'https://bugs.launchpad.net/bugs/'

    for bug in bugs:
        logging.info('%s%-7s - %-16s %-16s - %s',
                     bug_url, bug[0],
                     ('%s(%s)' % (('*' if bug[4] else ''), bug[3])),
                     ('[%s]' % bug[1]), bug[2])
        if open_in_browser:
            webbrowser.open("%s%s" % (bug_url, bug[0]))


def bug_info(bugs):
    """
    Collects the specific information for each bug entry.

    If detailed information is specified, than additional data is pulled
    in by the script, like last_updated, web link, title. This however
    takes a considerable amount of time.
    """
    bug_list = []
    for (bug, status, subscribed) in bugs:
        num = bug.split(' ')[1].replace('#', '')
        src = bug.split(' ')[3]
        title = ' '.join(bug.split(' ')[5:]).replace('"', '')
        bug_list.append((num, src, title, status, subscribed))

    bug_list.sort(key=lambda tup: tup[0])

    return bug_list


def modified_bugs(date, lpname, bugsubscriber):
    """
    Returns a list of bugs modified after a specific date.
    """
    already_sub_bugs = []
    # Distribution List: https://launchpad.net/distros
    # API Doc: https://launchpad.net/+apidoc/1.0.html
    launchpad = connect_launchpad()
    project = launchpad.distributions['Ubuntu']
    team = launchpad.people[lpname]

    if bugsubscriber:
        # direct subscriber
        raw_bugs = project.searchTasks(modified_since=date,
                                       bug_subscriber=team)
    else:
        # structural_subscriber sans already subscribed
        mod_bugs = project.searchTasks(modified_since=date,
                                       structural_subscriber=team)
        already_sub = project.searchTasks(modified_since=date,
                                          structural_subscriber=team,
                                          bug_subscriber=team)
        raw_bugs = [b for b in mod_bugs if b not in already_sub_bugs]

    bugs = [(bug.title, bug.status, (bug in already_sub)) for bug in raw_bugs]
    logging.debug('Bug count for %s: %s', date, len(bugs))

    return bugs


def create_bug_list(start_date, end_date, lpname, bugsubscriber, nodatefilter):
    """
    Subtracts all bugs modified after specified start and end dates.

    This provides the list of bugs between two dates as Launchpad does
    not appear to have a specific function for searching for a range.
    """
    logging.info('Please be paitent, this can take a few minutes...')
    start_date, end_date = check_dates(start_date, end_date, nodatefilter)

    start_bugs = modified_bugs(start_date, lpname, bugsubscriber)
    end_bugs = modified_bugs(end_date, lpname, bugsubscriber)
    bugs = [x for x in start_bugs if x not in end_bugs]

    bug_list = bug_info(bugs)

    logging.info('Found %s bugs', len(bug_list))
    logging.info('---')

    return bug_list

def report_current_backlog(lpname):
    """
    Reports how much bugs the team is currently subscribed to.

    This value is usually needed to track how the backlog is growing/shrinking.
    """
    launchpad = connect_launchpad()
    project = launchpad.distributions['Ubuntu']
    team = launchpad.people[lpname]
    sub_bugs = project.searchTasks(bug_subscriber=team)
    logging.info('Team %s currently subscribed to %d bugs',
                 lpname, len(sub_bugs))

def main(start=None, end=None, open_in_browser=False, lpname="ubuntu-server",
         bugsubscriber=False, nodatefilter=False, shortlinks=True):
    """
    Connect to Launchpad, get range of bugs, print 'em.
    """
    logging.basicConfig(stream=sys.stdout, format='%(message)s',
                        level=LOG_LEVEL)

    connect_launchpad()
    logging.info('Ubuntu Server Bug List')
    bugs = create_bug_list(start, end, lpname, bugsubscriber, nodatefilter)
    report_current_backlog(lpname)
    print_bugs(bugs, open_in_browser, shortlinks)


if __name__ == '__main__':
    PARSER = argparse.ArgumentParser()
    PARSER.add_argument('start_date',
                        nargs='?',
                        help='date to start finding bugs ' +
                        '(e.g. 2016-07-15)')
    PARSER.add_argument('end_date',
                        nargs='?',
                        help='date to end finding bugs (inclusive) ' +
                        '(e.g. 2016-07-31)')
    PARSER.add_argument('-d', '--debug', action='store_true',
                        help='debug output')
    PARSER.add_argument('-o', '--open', action='store_true',
                        help='open in web browser')
    PARSER.add_argument('-a', '--nodatefilter', action='store_true',
                        help='show all (no date restriction)')
    PARSER.add_argument('-n', '--lpname', default='ubuntu-server',
                        help='specify the launchpad name to search for')
    PARSER.add_argument('-b', '--bugsubscriber', action='store_true',
                        help=('filter name as bug subscriber (default would '
                              'be structural subscriber'))
    PARSER.add_argument('--fullurls', default=False, action='store_true',
                        help='show full URLs instead of shortcuts')


    ARGS = PARSER.parse_args()

    if ARGS.debug:
        LOG_LEVEL = logging.DEBUG

    main(ARGS.start_date, ARGS.end_date, ARGS.open, ARGS.lpname,
         ARGS.bugsubscriber, ARGS.nodatefilter, not ARGS.fullurls)
