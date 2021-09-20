#!/usr/bin/env python3
"""
Output Ubuntu Server Launchpad bugs that for triage.

Script accepts either a single date or inclusive range to find bugs.

Copyright 2017-2021 Canonical Ltd.
Joshua Powers <josh.powers@canonical.com>
Christian Ehrhardt <christian.ehrhardt@canonical.com>
"""
import argparse
from datetime import date, datetime, timedelta
import logging
import os
import re
import sys
import time
import webbrowser

import dateutil.parser
import dateutil.relativedelta
from launchpadlib.launchpad import Launchpad
from launchpadlib.credentials import UnencryptedFileCredentialStore

from lazr.restfulclient.errors import ClientError

from .task import Task

PACKAGE_BLACKLIST = {
    'cloud-init',
    'curtin',
    'juju',
    'juju-core',
    'lxc',
    'lxd',
    'maas',
    'ubuntu-advantage-tools',
}
TEAMLPNAME = "ubuntu-server"

POSSIBLE_BUG_STATUSES = [
    "New",
    "Incomplete",
    "Opinion",
    "Invalid",
    "Won't Fix",
    "Expired",
    "Confirmed",
    "Triaged",
    "In Progress",
    "Fix Committed",
    "Fix Released",
]

OPEN_BUG_STATUSES = [
    "New",
    "Confirmed",
    "Triaged",
    "In Progress",
    "Fix Committed",
]

TRACKED_BUG_STATUSES = OPEN_BUG_STATUSES + [
    "Incomplete",
]

DISTRIBUTION_RESOURCE_TYPE_LINK = (
    'https://api.launchpad.net/devel/#distribution'
)


def fast_target_name(obj):
    """Return the name of a bug task's target.

    This is an optimisation hack that saves us from fetching the target object
    in order to determine its name.

    :param obj: bug_task object from launchpadlib
    :returns: the equivalent of obj.target.name
    """
    return obj.target_link.split('/')[-1]


def searchTasks_in_all_active_series(distro, *args, **kwargs):  # noqa: E501 pylint: disable=invalid-name
    """Unionize searchTasks() for all active series of a distribution.

    A searchTasks() Launchpad call against a Launchpad distribution will not
    return series tasks if the development task is marked Fix Released (LP:
    #314432; see also comment 26 in that bug). The workaround is to call
    searchTasks() individually against both the distribution object itself and
    also against all required series and unionize the results. This function
    provides an implementation of this workaround.

    One difference to calling searchTasks() directly is that the tasks returned
    by this function are targetted either to the distribution or to particular
    series. It is not possible to return tasks targetted just to the
    distribution in the general case because no such tasks exist for bugs where
    the development task is marked Fix Released (the exact case we're fixing).

    This implementation returns only one series task for each found bug and
    package name, not all of them. An arbitrary task is picked. Only active
    serieses are considered.

    :param distro: distribution object from launchpadlib
    :param *args: arguments to pass to the wrapped searchTasks calls
    :param **kargs: arguments to pass to the wrapped searchTasks calls
    :rtype: sequence(bug_task object from launchpadlib)
    """
    # This workaround implementation is to be called on distribution objects
    # only; other objects (typically a series directly) are not affected, and
    # the caller shouldn't be using this workaround in that case. If needed, we
    # could modify this to wrap searchTasks for other object types if we don't
    # want the caller to have to know which to use, but YAGNI for now.
    assert distro.resource_type_link == DISTRIBUTION_RESOURCE_TYPE_LINK

    result = {
        (task.bug_link, fast_target_name(task)): task
        for task in distro.searchTasks(*args, **kwargs)
    }
    for series in distro.series_collection:
        if not series.active:
            continue
        # Deduplicate against the bug number and source package name as a
        # key. Keying additionally on the distribution is not required
        # because all results must be against the same distribution since
        # that's what we queried against. Here, "target" must be a
        # source_package object because we queried specifically against a
        # distro_series so we can assume that a name attribute is always
        # present.
        result.update({
            (task.bug_link, fast_target_name(task)): task
            for task in series.searchTasks(*args, **kwargs)
        })

    return result.values()


def auto_date_range(keyword, today=None):
    """Given a "day of week" keyword, calculate the inclusive date range.

    Work out what date range the user "means" based on the Server Team's bug
    triage process that names the day the triage is expected to be done.

    Examples: "Monday triage" means the range covering the previous Friday,
    Saturday and Sunday; "Tuesday triage" means the previous Monday only.

    :param str keyword: what the user wants in the form of the name of a day of
        the week
    :param datetime.date today: calculations are made relative to the current
        date. Can be overridden with this parameter for tests. Defaults to the
        current day
    :rtype: tuple(datetime.date, datetime.date)
    """
    today = today or date.today()
    requested_weekday = dateutil.parser.parse(keyword, ignoretz=True).weekday()
    last_occurrence = today + dateutil.relativedelta.relativedelta(
        weekday=dateutil.relativedelta.weekday(requested_weekday, -1)
    )
    if requested_weekday in [5, 6]:
        raise ValueError("No triage range is specified for weekday triage")

    if last_occurrence.weekday():
        # A Monday was not specified, so this is normal "previous day" triage
        start = last_occurrence + dateutil.relativedelta.relativedelta(days=-1)
        end = start
    else:
        # A Monday was specified, so this is "weekend" triage
        start = last_occurrence + dateutil.relativedelta.relativedelta(
            weekday=dateutil.relativedelta.FR(-1)
        )
        end = last_occurrence + dateutil.relativedelta.relativedelta(
            weekday=dateutil.relativedelta.SU(-1)
        )

    return start, end


def reverse_auto_date_range(start, end):
    """Given a date range, return the "triage day" if it fits the process.

    This is the inverse of auto_date_range(). If the range matches a known
    range the fits the process, describe the range as a string such as "Monday
    triage". If no match, return None.

    :param datetime.date start: the start of the range (inclusive)
    :param datetime.date end: the end of the range (inclusive)
    :returns: string describing the triage, or None
    :rtype: str or None
    """
    if start > end:
        return None  # process not specified
    if (end - start).days > 2:
        return None  # not a day or weekend triage range: process not specified

    start_weekday = start.weekday()
    end_weekday = end.weekday()

    if start_weekday == 4 and end_weekday == 6:
        return "Monday triage"

    if start == end:
        if start_weekday in [4, 5, 6]:
            return None  # weekend: process not specified

        # must be regular day triage
        day = ['Tuesday', 'Wednesday', 'Thursday', 'Friday'][start_weekday]
        return "%s triage" % day

    return None


def connect_launchpad():
    """Use the launchpad module connect to launchpad.

    Will connect you to the Launchpad website the first time you run
    this to authorize your system to connect.
    """
    cred_location = os.path.expanduser('~/.lp_creds')
    credential_store = UnencryptedFileCredentialStore(cred_location)
    return Launchpad.login_with('ustriage', 'production', version='devel',
                                credential_store=credential_store)


def parse_dates(start, end=None):
    """Validate dates are setup correctly."""
    # if start date is not set we search all bugs of a LP user/team
    if not start:
        logging.info('No date set, auto-search yesterday/weekend for the '
                     'most common triage.')
        yesterday = datetime.now().date() - timedelta(days=1)
        if yesterday.weekday() != 6:
            start = yesterday.strftime('%Y-%m-%d')
        else:
            # include weekend if yesterday was a sunday
            start = (yesterday - timedelta(days=2)).strftime('%Y-%m-%d')
            end = yesterday.strftime('%Y-%m-%d')

    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', start):
        # If end date is not set set it to start so we can
        # properly show the inclusive list of dates.
        if not end:
            end = start

    elif start and not end:
        try:
            start_date, end_date = auto_date_range(start)
            start = start_date.strftime('%Y-%m-%d')
            end = end_date.strftime('%Y-%m-%d')
        except ValueError as error:
            raise ValueError("Cannot parse date: %s" % start) from error

    else:
        raise ValueError("Cannot parse date range: %s %s" % (start, end))

    # Always add one to end date to make the dates inclusive
    end = datetime.strptime(end, '%Y-%m-%d') + timedelta(days=1)
    end = end.strftime('%Y-%m-%d')

    return start, end


def print_bugs(tasks, open_in_browser=False, shortlinks=True, blacklist=None,
               limit_backlog=None):
    """Print the tasks in a clean-ish format."""
    blacklist = blacklist or []

    sorted_filtered_tasks = sorted(
        (t for t in tasks if t.src not in blacklist),
        key=Task.sort_key,
    )

    logging.info('Found %s bugs', len(sorted_filtered_tasks))

    if limit_backlog is not None and len(sorted_filtered_tasks) > limit_backlog:
        logging.info('Displaying top & bottom %s', limit_backlog)
        logging.info('# Recent tasks #')
        print_bugs(sorted_filtered_tasks[:limit_backlog],
                   open_in_browser, shortlinks, None, None)
        logging.info('---------------------------------------------------')
        logging.info('# Oldest tasks #')
        # https://github.com/PyCQA/pylint/issues/1472
        # pylint: disable=invalid-unary-operand-type
        print_bugs(sorted_filtered_tasks[-limit_backlog:],
                   open_in_browser, shortlinks, None, None)
        return

    opened = False
    reportedbugs = []
    for task in sorted_filtered_tasks:
        if task.number in reportedbugs:
            print(task.compose_dup(shortlinks=shortlinks))
            continue

        print(task.compose_pretty(shortlinks=shortlinks))

        if open_in_browser:
            if opened:
                webbrowser.open_new_tab(task.url)
                time.sleep(1.2)
            else:
                webbrowser.open(task.url)
                opened = True
                time.sleep(5)
        reportedbugs.append(task.number)


def last_activity_ours(task, activitysubscribers):
    """Work out whether the last person to work on this bug was one of us.

    task: a Launchpad task object
    activitysubscribers: a set of Launchpad person objects

    Returns a boolean
    """
    # If activitysubscribers is empty, then it wasn't one of us
    if not activitysubscribers:
        return False

    activitysubscribers_links = {p.self_link for p in activitysubscribers}

    # 1. activity_list shall contain a tuple of (date, person.self_link) pairs
    # 2. messages collection is ordered and the last few elements are enough
    # This avoid too many API round trips to launchpad. With 0.1-0.5 seconds
    # per round trip and some overhead that is ~1.7s per bug now compared to
    # the former rather excessive times on bugs with many comments
    # Note: negative like [-3:] slices are not allowed here
    activity_list = []
    last_msgs_end = len(task.bug.messages)
    last_msgs_start = 0 if last_msgs_end < 3 else last_msgs_end-3
    for msg in task.bug.messages[last_msgs_start:last_msgs_end]:
        try:
            activity_list.append((msg.date_created, msg.owner.self_link))
        except ClientError as exc:
            if exc.response["status"] == "410":  # gone, user suspended
                continue
            raise

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


def create_bug_list(
        start_date, end_date, lpname, bugsubscriber, activitysubscribers,
        tag=None, status=POSSIBLE_BUG_STATUSES
):  # pylint: disable=dangerous-default-value
    """Return a list of bugs modified between dates."""
    # Distribution List: https://launchpad.net/distros
    # API Doc: https://launchpad.net/+apidoc/1.0.html
    launchpad = connect_launchpad()
    project = launchpad.distributions['Ubuntu']
    team = launchpad.people[lpname]

    if start_date is not None and end_date is not None:
        if bugsubscriber:
            # direct subscriber
            bugs_since_start = {
                task.self_link: task for task in
                searchTasks_in_all_active_series(
                    project,
                    modified_since=start_date, bug_subscriber=team, tags=tag,
                    tags_combinator='All',
                    status=status,
                )}
            bugs_since_end = {
                task.self_link: task for task in
                searchTasks_in_all_active_series(
                    project,
                    modified_since=end_date, bug_subscriber=team, tags=tag,
                    tags_combinator='All',
                    status=status,
                )}

            # N/A for direct subscribers
            already_sub_since_start = {}

        else:
            # structural_subscriber sans already subscribed
            bugs_since_start = {
                task.self_link: task for task in
                searchTasks_in_all_active_series(
                    project,
                    modified_since=start_date, structural_subscriber=team,
                    status=status,
                )}
            bugs_since_end = {
                task.self_link: task for task in
                searchTasks_in_all_active_series(
                    project,
                    modified_since=end_date, structural_subscriber=team,
                    status=status,
                )}
            already_sub_since_start = {
                task.self_link: task for task in
                searchTasks_in_all_active_series(
                    project,
                    modified_since=start_date, structural_subscriber=team,
                    bug_subscriber=team,
                    status=status,
                )}

        bugs_in_range = {
            link: task for link, task in bugs_since_start.items()
            if link not in bugs_since_end
        }
    else:
        # in bug-scrub we want all, even those already subscribed
        already_sub_since_start = {}
        if bugsubscriber:
            # direct subscriber
            bugs_in_range = {
                task.self_link: task for task in
                searchTasks_in_all_active_series(
                    project,
                    bug_subscriber=team, tags=tag,
                    tags_combinator='All',
                    status=status,
                )}
        else:
            # structural_subscriber sans already subscribed
            bugs_in_range = {
                task.self_link: task for task in
                searchTasks_in_all_active_series(
                    project,
                    structural_subscriber=team,
                    status=status,
                )}

    bugs = {
        Task.create_from_launchpadlib_object(
            task,
            subscribed=(link in already_sub_since_start),
            last_activity_ours=last_activity_ours(task, activitysubscribers),
        )
        for link, task in bugs_in_range.items()
    }

    return bugs


def report_current_backlog(lpname):
    """Report how many bugs the team is currently subscribed to.

    This value is usually needed to track how the backlog is growing/shrinking.
    """
    launchpad = connect_launchpad()
    project = launchpad.distributions['Ubuntu']
    team = launchpad.people[lpname]
    sub_bugs_count = len(set((
        task.bug_link for task in searchTasks_in_all_active_series(
            project,
            bug_subscriber=team,
            status=OPEN_BUG_STATUSES,
        )
    )))
    logging.info(
        'Team \'%s\' currently subscribed to %d bugs',
        lpname,
        sub_bugs_count,
    )


def print_tagged_bugs(lpname, expiration, date_range, open_browser,
                      shortlinks, blacklist, activitysubscribers):
    """Print bugs tagged with server-next.

    Print tagged bugs, optionally those that have not been
    touched in a while.
    """
    logging.info('')
    logging.info('---')

    if expiration is None:
        logging.info('Bugs tagged "server-next"')
        expire_start = None
        expire_end = None
        wanted_statuses = TRACKED_BUG_STATUSES
    else:
        logging.info('Bugs tagged "server-next" and not touched in %s days',
                     expiration['expire_next'])
        expire_start = (datetime.strptime(date_range['start'], '%Y-%m-%d')
                        - timedelta(days=expiration['expire_next']))
        expire_end = (datetime.strptime(date_range['end'], '%Y-%m-%d')
                      - timedelta(days=expiration['expire_next']))
        expire_start = expire_start.strftime('%Y-%m-%d')
        expire_end = expire_end.strftime('%Y-%m-%d')
        wanted_statuses = OPEN_BUG_STATUSES

    bugs = create_bug_list(
        expire_start,
        expire_end,
        lpname, TEAMLPNAME, activitysubscribers,
        tag=["server-next", "-bot-stop-nagging"],
        status=wanted_statuses
    )
    print_bugs(bugs, open_browser['exp'], shortlinks,
               blacklist=blacklist)


def print_backlog_bugs(lpname, expiration, date_range, open_browser,
                       shortlinks, blacklist, limit_backlog):
    """Print bugs in the backlog that have not been touched in a while."""
    logging.info('')
    logging.info('---')
    if expiration is None:
        logging.info('Bugs in backlog')
        expire_start = None
        expire_end = None
        tag = ["-bot-stop-nagging", "-server-next"]
    else:
        logging.info('Bugs in backlog and not touched in %s days',
                     expiration['expire'])
        expire_start = (datetime.strptime(date_range['start'], '%Y-%m-%d')
                        - timedelta(days=expiration['expire']))
        expire_end = (datetime.strptime(date_range['end'], '%Y-%m-%d')
                      - timedelta(days=expiration['expire']))
        expire_start = expire_start.strftime('%Y-%m-%d')
        expire_end = expire_end.strftime('%Y-%m-%d')
        tag = "-bot-stop-nagging"

    bugs = create_bug_list(
        expire_start,
        expire_end,
        lpname, TEAMLPNAME, None,
        tag=tag,
        status=OPEN_BUG_STATUSES,
    )
    print_bugs(bugs, open_browser['exp'], shortlinks,
               blacklist=blacklist, limit_backlog=limit_backlog)


def main(date_range=None, debug=False, open_browser=None,
         lpname=TEAMLPNAME, bugsubscriber=False, shortlinks=True,
         activitysubscribernames=None, expiration=None, bug_scrub=False,
         limit_backlog=None, blacklist=None):
    """Connect to Launchpad, get range of bugs, print 'em."""
    launchpad = connect_launchpad()
    logging.basicConfig(stream=sys.stdout, format='%(message)s',
                        level=logging.DEBUG if debug else logging.INFO)
    if activitysubscribernames:
        activitysubscribers = (
            launchpad.people[activitysubscribernames].members
        )
    else:
        activitysubscribers = []

    logging.info('Ubuntu Server Triage helper')
    logging.info('Please be patient, this can take a few minutes...')

    if bug_scrub:
        print_tagged_bugs(lpname, None, None, open_browser,
                          shortlinks, blacklist, activitysubscribers)
        print_backlog_bugs(lpname, None, None,
                           open_browser, shortlinks, blacklist, limit_backlog)
        return

    report_current_backlog(lpname)
    date_range['start'], date_range['end'] = parse_dates(date_range['start'],
                                                         date_range['end'])

    logging.info('---')
    # Need to display date range as inclusive
    inclusive_start = datetime.strptime(date_range['start'], '%Y-%m-%d')
    inclusive_end = (
        datetime.strptime(date_range['end'], '%Y-%m-%d') -
        timedelta(days=1)
    )
    pretty_start = inclusive_start.strftime('%Y-%m-%d (%A)')
    pretty_end = inclusive_end.strftime('%Y-%m-%d (%A)')
    logging.info('\'*\': %s is directly subscribed', lpname)
    logging.info('\'+\': last bug activity is ours')
    if inclusive_start == inclusive_end:
        logging.info(
            'Bugs last updated on %s',
            pretty_start,
        )
    else:
        logging.info(
            'Bugs last updated between %s and %s inclusive',
            pretty_start,
            pretty_end
        )

    triage_day_name = reverse_auto_date_range(inclusive_start, inclusive_end)
    if triage_day_name:
        logging.info("Date range identified as: \"%s\"", triage_day_name)

    bugs = create_bug_list(
        date_range['start'], date_range['end'],
        lpname, bugsubscriber, activitysubscribers
    )
    print_bugs(bugs, open_browser['triage'], shortlinks, blacklist=blacklist)

    if expiration['show_expiration']:
        print_tagged_bugs(lpname, expiration, date_range, open_browser,
                          shortlinks, blacklist, activitysubscribers)
        print_backlog_bugs(lpname, expiration, date_range,
                           open_browser, shortlinks, blacklist, None)


def launch():
    """Parse arguments provided."""
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
    parser.add_argument('-O', '--open-expire', action='store_true',
                        dest='openexp',
                        help='open expiring bugs in web browser')
    parser.add_argument('-n', '--lpname', default=TEAMLPNAME,
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
    parser.add_argument('--no-blacklist', action='store_true',
                        help='do not use the package blacklist')
    parser.add_argument('-e', '--no-expiration',
                        default=True,
                        action='store_false',
                        dest='show_expiration',
                        help='Do not report about expiration of bugs')
    parser.add_argument('--expire-next',
                        default=60,
                        type=int,
                        dest='expire_next',
                        help='Days to consider bugs that should be handled'
                        ' next expired')
    parser.add_argument('--expire',
                        default=180,
                        type=int,
                        dest='expire',
                        help='Days to consider bugs expired')
    parser.add_argument('--tag-next',
                        default='server-next',
                        dest='tag_next',
                        help='Tag that marks bugs to be handled soon')
    parser.add_argument('-B', '--bug-scrub',
                        default=False,
                        action='store_true',
                        dest='bug_scrub',
                        help='Display current server-next and '
                             'server-subscribed bugs (all Date/Expiration ')
    parser.add_argument('--limit-backlog',
                        default=20,
                        type=int,
                        dest='limit_backlog',
                        help='Limits the bug-scrub backlog report to the top '
                             'and bottom number of tasks')

    args = parser.parse_args()

    open_browser = {'triage': args.open,
                    'exp': args.openexp}
    expiration = {'expire_next': args.expire_next,
                  'expire': args.expire,
                  'tag_next': args.tag_next,
                  'show_expiration': args.show_expiration}
    date_range = {'start': args.start_date,
                  'end': args.end_date}

    main(date_range, args.debug, open_browser,
         args.lpname, args.bugsubscriber, not args.fullurls,
         args.activitysubscribers, expiration,
         args.bug_scrub, args.limit_backlog,
         blacklist=None if args.no_blacklist else PACKAGE_BLACKLIST)


if __name__ == '__main__':
    launch()
