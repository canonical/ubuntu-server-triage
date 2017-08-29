#!/usr/bin/env python3
"""
Output Ubuntu Server Launchpad bugs that for triage. Script accepts either
a single date or inclusive range to find bugs.

Copyright 2017 Canonical Ltd.
Joshua Powers <josh.powers@canonical.com>
"""
import argparse
from datetime import datetime, timedelta
import logging
import os
import sys
import webbrowser

from launchpadlib.launchpad import Launchpad
from launchpadlib.credentials import UnencryptedFileCredentialStore

from lazr.restfulclient.errors import ClientError

from task import Task

PACKAGE_BLACKLIST = {
    'cloud-init',
    'curtin',
    'juju',
    'juju-core',
    'lxc',
    'lxd',
    'maas',
}
TEAMLPNAME = "ubuntu-server"


def connect_launchpad():
    """
    Using the launchpad module connect to launchpad.

    Will connect you to the Launchpad website the first time you run
    this to autorize your system to connect.
    """
    cred_location = os.path.expanduser('~/.lp_creds')
    credential_store = UnencryptedFileCredentialStore(cred_location)
    return Launchpad.login_with('ustriage', 'production', version='devel',
                                credential_store=credential_store)


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

    # Always add one to end date to make the dates inclusive
    end = datetime.strptime(end, '%Y-%m-%d') + timedelta(days=1)
    end = end.strftime('%Y-%m-%d')

    return start, end


def print_bugs(tasks, open_in_browser=False, shortlinks=True, blacklist=None):
    """
    Prints the tasks in a clean-ish format.
    """
    blacklist = blacklist or []

    sorted_filtered_tasks = sorted(
        (t for t in tasks if t.src not in blacklist),
        key=Task.sort_key,
    )

    logging.info('Found %s bugs', len(sorted_filtered_tasks))

    for task in sorted_filtered_tasks:
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
    unsorted_list = []
    for m in task.bug.messages:
        try:
            unsorted_list.append((m.date_created, m.owner.self_link))
        except ClientError as e:
            if e.response["status"] == "410": # gone, user suspended
                continue
            raise
    activity_list = sorted(unsorted_list, key=lambda a: a[0])

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


def create_bug_list(start_date, end_date, lpname, bugsubscriber,
                    activitysubscribers, tag=None):
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
                modified_since=start_date, bug_subscriber=team, tags=tag,
                tags_combinator='All'
            )}
        bugs_since_end = {
            task.self_link: task for task in project.searchTasks(
                modified_since=end_date, bug_subscriber=team, tags=tag,
                tags_combinator='All'
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


def report_current_backlog(lpname):
    """
    Reports how much bugs the team is currently subscribed to.

    This value is usually needed to track how the backlog is growing/shrinking.
    """
    launchpad = connect_launchpad()
    project = launchpad.distributions['Ubuntu']
    team = launchpad.people[lpname]
    sub_bugs = project.searchTasks(bug_subscriber=team)
    logging.info('Team \'%s\' currently subscribed to %d bugs',
                 lpname, len(sub_bugs))


def print_expired_tagged_bugs(lpname, expiration, date_range, open_browser,
                              shortlinks, blacklist):
    """Prints bugs with server-next that have not been touched in a while."""
    logging.info('')
    logging.info('---')
    logging.info('Bugs tagged \'%s\' and not touched in %s days',
                 expiration['tag_next'], expiration['expire_next'])
    expire_start = (datetime.strptime(date_range['start'], '%Y-%m-%d')
                    - timedelta(days=expiration['expire_next']))
    expire_end = (datetime.strptime(date_range['end'], '%Y-%m-%d')
                  - timedelta(days=expiration['expire_next']))
    expire_start = expire_start.strftime('%Y-%m-%d')
    expire_end = expire_end.strftime('%Y-%m-%d')
    bugs = create_bug_list(expire_start,
                           expire_end,
                           lpname, TEAMLPNAME, None,
                           tag=["server-next", "-bot-stop-nagging"])
    print_bugs(bugs, open_browser['exp'], shortlinks,
               blacklist=blacklist)


def print_expired_backlog_bugs(lpname, expiration, date_range, open_browser,
                               shortlinks, blacklist):
    """Prints bugs in the backlog that have not been touched in a while."""
    logging.info('')
    logging.info('---')
    logging.info('Bugs in backlog and not touched in %s days',
                 expiration['expire'])
    expire_start = (datetime.strptime(date_range['start'], '%Y-%m-%d')
                    - timedelta(days=expiration['expire']))
    expire_end = (datetime.strptime(date_range['end'], '%Y-%m-%d')
                  - timedelta(days=expiration['expire']))
    expire_start = expire_start.strftime('%Y-%m-%d')
    expire_end = expire_end.strftime('%Y-%m-%d')
    bugs = create_bug_list(expire_start,
                           expire_end,
                           lpname, TEAMLPNAME, None,
                           tag="-bot-stop-nagging")
    print_bugs(bugs, open_browser['exp'], shortlinks,
               blacklist=blacklist)


def main(date_range=None, debug=False, open_browser=None,
         lpname=TEAMLPNAME, bugsubscriber=False, nodatefilter=False,
         shortlinks=True, activitysubscribernames=None, expiration=None,
         blacklist=None):
    """
    Connect to Launchpad, get range of bugs, print 'em.
    """
    launchpad = connect_launchpad()
    logging.basicConfig(stream=sys.stdout, format='%(message)s',
                        level=logging.DEBUG if debug else logging.INFO)

    logging.info('Ubuntu Server Bug List')
    logging.info('Please be patient, this can take a few minutes...')
    report_current_backlog(lpname)
    if activitysubscribernames:
        activitysubscribers = (
            launchpad.people[activitysubscribernames].members
        )
    else:
        activitysubscribers = []

    date_range['start'], date_range['end'] = check_dates(date_range['start'],
                                                         date_range['end'],
                                                         nodatefilter)

    logging.info('---')
    # Need to make date range inclusive
    end = datetime.strptime(date_range['end'], '%Y-%m-%d') - timedelta(days=1)
    end = end.strftime('%Y-%m-%d')
    logging.info('\'*\': %s is directly subscribed', lpname)
    logging.info('\'†\': last bug activity is ours')
    logging.info('Bugs for triage on %s to %s (inclusive)',
                 date_range['start'], end)

    bugs = create_bug_list(
        date_range['start'], date_range['end'],
        lpname, bugsubscriber, activitysubscribers
    )
    print_bugs(bugs, open_browser['triage'], shortlinks, blacklist=blacklist)

    if expiration['show_expiration']:
        print_expired_tagged_bugs(lpname, expiration, date_range, open_browser,
                                  shortlinks, blacklist)
        print_expired_backlog_bugs(lpname, expiration, date_range,
                                   open_browser, shortlinks, blacklist)


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
    parser.add_argument('-O', '--open-expire', action='store_true',
                        dest='openexp',
                        help='open expiring bugs in web browser')
    parser.add_argument('-a', '--nodatefilter', action='store_true',
                        help='show all (no date restriction)')
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
                        dest='expire_next',
                        help='Days to consider bugs that should be handled'
                        ' next expired')
    parser.add_argument('--expire',
                        default=180,
                        dest='expire',
                        help='Days to consider bugs expired')
    parser.add_argument('--tag-next',
                        default='server-next',
                        dest='tag_next',
                        help='Tag that marks bugs to be handled soon')

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
         args.lpname, args.bugsubscriber, args.nodatefilter, not args.fullurls,
         args.activitysubscribers, expiration,
         blacklist=None if args.no_blacklist else PACKAGE_BLACKLIST)


if __name__ == '__main__':
    launch()
