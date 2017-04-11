#!/usr/bin/env python3
"""
Output Ubuntu Server Launchpad bugs that for triage. Script accepts either
a single date or inclusive range to find bugs.

Copyright 2016 Canonical Ltd.
Joshua Powers <josh.powers@canonical.com>
"""
import argparse
from datetime import datetime, timedelta
from functools import lru_cache
import logging
import sys
import webbrowser

from launchpadlib.launchpad import Launchpad


class Task(object):
    """
    Our representation of a Launchpad task.

    This encapsulates a launchpadlib Task object, caches some queries,
    stores some other properties (eg. the team-"subscribed"-ness) as needed
    by callers, and presents a bunch of derived properties. All Task property
    specific handling is encapsulated here.
    """
    LONG_URL_ROOT = 'https://bugs.launchpad.net/bugs/'
    SHORTLINK_ROOT = 'LP: #'
    BUG_NUMBER_LENGTH = 7

    def __init__(self):
        # Whether the team is subscribed to the bug
        self.subscribed = None
        # Whether the last activity was by us
        self.last_activity_ours = None
        self.obj = None

    @staticmethod
    def create_from_launchpadlib_object(obj, **kwargs):
        """Create object from launchpadlib"""
        self = Task()
        self.obj = obj
        for key, value in kwargs.items():
            setattr(self, key, value)
        return self

    @property
    def url(self):
        """The user-facing URL of the task"""
        return self.LONG_URL_ROOT + self.number

    @property
    def shortlink(self):
        """The user-facing "shortlink" that gnome-terminal will autolink"""
        return self.SHORTLINK_ROOT + self.number

    @property
    @lru_cache()
    def number(self):
        """The bug number as a string"""
        # This could be str(self.obj.bug.id) but using self.title is
        # significantly faster
        return self.title.split(' ')[1].replace('#', '')

    @property
    @lru_cache()
    def src(self):
        # This could be self.target.name but using self.title is
        # significantly faster
        """The source package name"""
        return self.title.split(' ')[3]

    @property
    @lru_cache()
    def title(self):
        """The "title" as returned by launchpadlib"""
        return self.obj.title

    @property
    @lru_cache()
    def status(self):
        """The "status" as returned by launchpadlib"""
        return self.obj.status

    @property
    @lru_cache()
    def short_title(self):
        """Just the bug summary"""
        # This could be self.obj.bug.title but using self.title is
        # significantly faster
        return ' '.join(self.title.split(' ')[5:]).replace('"', '')

    def compose_pretty(self, shortlinks=True):
        """Compose a printable line of relevant information"""
        if shortlinks:
            format_string = (
                '%-' +
                str(self.BUG_NUMBER_LENGTH + len(self.SHORTLINK_ROOT)) +
                's'
            )
            bug_url = format_string % self.shortlink
        else:
            format_string = (
                '%-' +
                str(self.BUG_NUMBER_LENGTH + len(self.LONG_URL_ROOT)) +
                's'
            )
            bug_url = format_string % self.url

        flags = '%s%s' % (
            '*' if self.subscribed else '',
            '†' if self.last_activity_ours else '',
        )

        return '%s - %-16s %-16s - %s' % (
            bug_url,
            ('%s(%s)' % (flags, self.status)),
            ('[%s]' % self.src), self.short_title
        )

    def sort_key(self):
        return (not self.last_activity_ours, self.src)


def connect_launchpad():
    """
    Using the launchpad module connect to launchpad.

    Will connect you to the Launchpad website the first time you run
    this to autorize your system to connect.
    """
    return Launchpad.login_with('ubuntu-server-triage.py', 'production')


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


def print_bugs(tasks, open_in_browser=False, shortlinks=True):
    """
    Prints the tasks in a clean-ish format.
    """

    for task in sorted(tasks, key=Task.sort_key):
        logging.info(task.compose_pretty(shortlinks=shortlinks))
        if open_in_browser:
            webbrowser.open(task.url)


def last_activity_ours(task, activitysubscribers):
    """
    Work out whether the last person to work on this bug was one of us

    task: a Launchpad task object
    activitysubscribers: a set of Launchpad person objects

    Returns a boolean
    """

    # If activitysubscribers is empty, then it wasn't one of us
    if not activitysubscribers:
        return False

    activitysubscribers_links = {p.self_link for p in activitysubscribers}

    # activity_list contains a tuple of (date, person.self_link) pairs
    activity_list = sorted(
        (
            [(m.date_created, m.owner.self_link) for m in task.bug.messages]
        ),
        key=lambda a: a[0],
    )

    most_recent_activity = activity_list.pop()

    # Consider anything within an hour of the last activity or message as
    # part of the same action
    recent_activity_threshold = (
        most_recent_activity[0] - timedelta(hours=1)  # [0] is date
    )
    all_recent_activities = [most_recent_activity]

    for next_most_recent_activity in reversed(activity_list):
        if next_most_recent_activity[0] < recent_activity_threshold:
            break
        all_recent_activities.append(next_most_recent_activity)

    # If all of the last action was us, then treat it as ours. If any of the
    # last action wasn't done by us, then it isn't.
    return all(
        a[1] in activitysubscribers_links
        for a in all_recent_activities
    )


def modified_bugs(start_date, end_date, lpname, bugsubscriber,
                  activitysubscribers):
    """
    Returns a list of bugs modified between dates.
    """
    # Distribution List: https://launchpad.net/distros
    # API Doc: https://launchpad.net/+apidoc/1.0.html
    launchpad = connect_launchpad()
    project = launchpad.distributions['Ubuntu']
    team = launchpad.people[lpname]

    if bugsubscriber:
        # direct subscriber
        bugs_since_start = {
            task.self_link: task for task in project.searchTasks(
                modified_since=start_date, bug_subscriber=team
            )}
        bugs_since_end = {
            task.self_link: task for task in project.searchTasks(
                modified_since=end_date, bug_subscriber=team
            )}

        # N/A for direct subscribers
        already_sub_since_start = {}

    else:
        # structural_subscriber sans already subscribed
        bugs_since_start = {
            task.self_link: task for task in project.searchTasks(
                modified_since=start_date, structural_subscriber=team
            )}
        bugs_since_end = {
            task.self_link: task for task in project.searchTasks(
                modified_since=end_date, structural_subscriber=team
            )}
        already_sub_since_start = {
            task.self_link: task for task in project.searchTasks(
                modified_since=start_date, structural_subscriber=team,
                bug_subscriber=team
            )}

    bugs_in_range = {
        link: task for link, task in bugs_since_start.items()
        if link not in bugs_since_end
    }

    bugs = {
        Task.create_from_launchpadlib_object(
            task,
            subscribed=(link in already_sub_since_start),
            last_activity_ours=last_activity_ours(task, activitysubscribers),
        )
        for link, task in bugs_in_range.items()
    }

    return bugs


def create_bug_list(start_date, end_date, lpname, bugsubscriber, nodatefilter,
                    activitysubscribers):
    """
    Subtracts all bugs modified after specified start and end dates.

    This provides the list of bugs between two dates as Launchpad does
    not appear to have a specific function for searching for a range.
    """
    logging.info('Please be patient, this can take a few minutes...')
    start_date, end_date = check_dates(start_date, end_date, nodatefilter)

    tasks = modified_bugs(start_date, end_date, lpname, bugsubscriber,
                          activitysubscribers)

    logging.info('Found %s bugs', len(tasks))
    logging.info('---')

    return tasks


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
    logging.info('---')


def main(start=None, end=None, debug=False, open_in_browser=False,
         lpname="ubuntu-server", bugsubscriber=False, nodatefilter=False,
         shortlinks=True, activitysubscribernames=None):
    """
    Connect to Launchpad, get range of bugs, print 'em.
    """
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(stream=sys.stdout, format='%(message)s',
                        level=log_level)

    launchpad = connect_launchpad()
    logging.info('Ubuntu Server Bug List')
    report_current_backlog(lpname)
    if activitysubscribernames:
        activitysubscribers = (
            launchpad.people[activitysubscribernames].members
        )
    else:
        activitysubscribers = []
    bugs = create_bug_list(
        start, end, lpname, bugsubscriber, nodatefilter, activitysubscribers
    )
    print_bugs(bugs, open_in_browser, shortlinks)


def launch():
    """Parse arguments provided"""
    parser = argparse.ArgumentParser()
    parser.add_argument('start_date',
                        nargs='?',
                        help='date to start finding bugs ' +
                        '(e.g. 2016-07-15)')
    parser.add_argument('end_date',
                        nargs='?',
                        help='date to end finding bugs (inclusive) ' +
                        '(e.g. 2016-07-31)')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='debug output')
    parser.add_argument('-o', '--open', action='store_true',
                        help='open in web browser')
    parser.add_argument('-a', '--nodatefilter', action='store_true',
                        help='show all (no date restriction)')
    parser.add_argument('-n', '--lpname', default='ubuntu-server',
                        help='specify the launchpad name to search for')
    parser.add_argument('-b', '--bugsubscriber', action='store_true',
                        help=('filter name as bug subscriber (default would '
                              'be structural subscriber'))
    parser.add_argument('--fullurls', default=False, action='store_true',
                        help='show full URLs instead of shortcuts')
    parser.add_argument('--activitysubscribers',
                        default='ubuntu-server-active-triagers',
                        help='highlight when last touched by this LP team')
    parser.add_argument('--no-activitysubscribers',
                        action='store_const',
                        const=None,
                        dest='activitysubscribers',
                        help='unset the --activitysubscribers default')

    args = parser.parse_args()
    main(args.start_date, args.end_date, args.debug, args.open, args.lpname,
         args.bugsubscriber, args.nodatefilter, not args.fullurls,
         args.activitysubscribers)


if __name__ == '__main__':
    launch()
