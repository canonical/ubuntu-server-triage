#!/usr/bin/env python3
"""
Output Ubuntu Server Launchpad bugs that for triage.

Script accepts either a single date or inclusive range to find bugs.

Copyright 2017-2021 Canonical Ltd.
Joshua Powers <josh.powers@canonical.com>
Christian Ehrhardt <christian.ehrhardt@canonical.com>
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import logging
import os
import re
import sys
import time
import webbrowser
import yaml

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
DEFAULTTAG = "server-todo"
FLAG_RECENT_AGE = 6
FLAG_OLD_AGE = 90

# See the "Merge Board Coordination" specification for details about these tags
PACKAGING_TASK_TAGS = [
    'needs-merge',
    'needs-sync',
    'needs-oci-update',
    'needs-snap-update',
    'needs-mre-backport',
    'needs-ppa-backport',
]

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

STR_STRIKETHROUGH = '\u0336'


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


def handle_files(filename_save, filename_compare, reportedbugs, former_bugs,
                 shortlinks, extended):
    """Handle saving and comparing to saved lists of bugs."""
    if filename_save is not None:
        with open(filename_save, "w", encoding='utf-8') as savebugs:
            yaml.dump(reportedbugs, stream=savebugs)
        logging.info("Saved reported bugs in %s", filename_save)

    if filename_compare is not None:
        closed_bugs = [x for x in former_bugs if x not in reportedbugs]
        logging.info('')
        logging.info("Bugs gone compared with %s:", filename_compare)
        gone_tasks = bugs_to_tasks(closed_bugs)
        print_bugs(gone_tasks, open_in_browser=0,
                   shortlinks=shortlinks, is_sorted=True, extended=extended)


def handle_webbrowser(open_in_browser, url):
    """Rate limited opening of urls in the browser."""
    if open_in_browser > 1:
        webbrowser.open_new_tab(url)
        time.sleep(1.2)
    elif open_in_browser == 1:
        webbrowser.open(url)
        open_in_browser += 1
        time.sleep(5)


def print_bug_line(text, task, postponed_bugs):
    """Format each bug line, like strikethrough for postponed bugs."""
    if task.number in postponed_bugs:
        text = STR_STRIKETHROUGH.join(text)
    logging.info(text)


def load_former_bugs(filename_compare):
    """Load list of former bugs from yaml file."""
    former_bugs = []
    if filename_compare is not None:
        with open(filename_compare, "r", encoding='utf-8') as comparebugs:
            former_bugs = yaml.safe_load(comparebugs)
    return former_bugs


def load_postponed_bugs(filename_postponed):
    """Load list of postponed bugs from yaml file, checking the date."""
    postponed_bugs = []
    logging.info("\nPostponed bugs:")
    if filename_postponed is not None:
        with open(filename_postponed, "r", encoding='utf-8') as postponebugs:
            pbugs = yaml.safe_load(postponebugs)
            for pbug in pbugs:
                postpone_until = datetime.strptime(pbug[1], '%Y-%m-%d')
                if postpone_until.date() > datetime.now().date():
                    logging.info("%s postponed until %s", pbug[0],
                                 postpone_until.strftime('%Y-%m-%d'))
                    postponed_bugs.append(pbug[0])
    if not postponed_bugs:
        logging.info("<None>")
    logging.info("")
    return postponed_bugs


def print_bugs(tasks, open_in_browser=0, shortlinks=True, blacklist=None,
               limit_subscribed=None, oder_by_date=False, is_sorted=False,
               extended=False, filename_save=None, filename_compare=None,
               filename_postponed=None):
    """Print the tasks in a clean-ish format."""
    blacklist = blacklist or []

    if is_sorted:
        sorted_filtered_tasks = tasks
    else:
        sorted_filtered_tasks = sorted(
            (t for t in tasks if t.src not in blacklist),
            key=(Task.sort_date if oder_by_date else Task.sort_key),
            reverse=oder_by_date
        )

    if filename_compare is not None:
        former_bugs = load_former_bugs(filename_compare)
    if filename_postponed is not None:
        postponed_bugs = load_postponed_bugs(filename_postponed)

    logging.info('Found %s bugs\n', len(sorted_filtered_tasks))
    if len(sorted_filtered_tasks) == 0:
        # Do not print header or anything else if the list is empty
        return

    logging.info(Task.get_header(extended=extended))

    if (limit_subscribed is not None and
            len(sorted_filtered_tasks) > limit_subscribed):
        logging.info('Displaying top & bottom %s', limit_subscribed)
        logging.info('# Recent tasks #')
        print_bugs(sorted_filtered_tasks[:limit_subscribed],
                   open_in_browser, shortlinks, limit_subscribed=None,
                   oder_by_date=False, is_sorted=True, extended=extended)
        logging.info('---------------------------------------------------')
        logging.info('# Oldest tasks #')
        # https://github.com/PyCQA/pylint/issues/1472
        # pylint: disable=invalid-unary-operand-type
        print_bugs(sorted_filtered_tasks[-limit_subscribed:],
                   open_in_browser, shortlinks, limit_subscribed=None,
                   oder_by_date=False, is_sorted=True, extended=extended)
        return

    reportedbugs = []
    further_tasks = ""
    for task in sorted_filtered_tasks:
        if task.number in reportedbugs:
            if further_tasks != "":
                further_tasks += ", "
            else:
                further_tasks += "Also: "
            further_tasks += "[%s]" % task.compose_dup(extended=extended)
            continue
        if further_tasks:
            logging.info(further_tasks)
            further_tasks = ""

        newbug = filename_compare and task.number not in former_bugs
        bugtext = task.compose_pretty(shortlinks=shortlinks,
                                      extended=extended,
                                      newbug=newbug,
                                      open_bug_statuses=OPEN_BUG_STATUSES)
        print_bug_line(bugtext, task, postponed_bugs)

        handle_webbrowser(open_in_browser, task.url)
        reportedbugs.append(task.number)

    # There might be one set of further tasks left if no other bug followed
    if further_tasks:
        logging.info(further_tasks)
        further_tasks = ""

    handle_files(filename_save, filename_compare, reportedbugs, former_bugs,
                 shortlinks=shortlinks, extended=extended)


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
        tags=None, status=POSSIBLE_BUG_STATUSES
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
                    modified_since=start_date,
                    bug_subscriber=team,
                    tags=tags,
                    tags_combinator='All',
                    status=status,
                )}
            bugs_since_end = {
                task.self_link: task for task in
                searchTasks_in_all_active_series(
                    project,
                    modified_since=end_date,
                    bug_subscriber=team,
                    tags=tags,
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
        already_sub_since_start = {}
        if bugsubscriber:
            # direct subscriber
            bugs_in_range = {
                task.self_link: task for task in
                searchTasks_in_all_active_series(
                    project,
                    bug_subscriber=team,
                    tags=tags,
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


def bugs_to_tasks(bug_numbers):
    """Return a task structure for a given bug number."""
    # Distribution List: https://launchpad.net/distros
    # API Doc: https://launchpad.net/+apidoc/1.0.html
    launchpad = connect_launchpad()

    tasks = []
    for bug_number in bug_numbers:
        bug_tasks = launchpad.bugs[bug_number].bug_tasks
        for bug_task in bug_tasks:
            task = Task.create_from_launchpadlib_object(
                bug_task,
                subscribed=False,
                last_activity_ours=False
            )
            tasks.append(task)

    return tasks


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
                      shortlinks, blacklist, activitysubscribers,
                      tags, extended,
                      filename_save=None,
                      filename_compare=None, filename_postponed=None):
    """Print tagged bugs.

    Print tagged bugs, optionally those that have not been
    touched in a while.
    """
    if expiration is None:
        logging.info('Bugs tagged "%s" and subscribed "%s"', ' '.join(tags),
                     lpname)
        expire_start = None
        expire_end = None
        wanted_statuses = TRACKED_BUG_STATUSES
    else:
        logging.info('Bugs tagged "%s" and subscribed "%s" and not touched'
                     ' in %s days',
                     ' '.join(tags), lpname, expiration['expire_tagged'])
        expire_start = (datetime.strptime(date_range['start'], '%Y-%m-%d')
                        - timedelta(days=expiration['expire_tagged']))
        expire_end = (datetime.strptime(date_range['end'], '%Y-%m-%d')
                      - timedelta(days=expiration['expire_tagged']))
        expire_start = expire_start.strftime('%Y-%m-%d')
        expire_end = expire_end.strftime('%Y-%m-%d')
        wanted_statuses = OPEN_BUG_STATUSES

    bugs = create_bug_list(
        expire_start,
        expire_end,
        lpname, TEAMLPNAME, activitysubscribers,
        tags=tags + ["-bot-stop-nagging"],
        status=wanted_statuses
    )
    print_bugs(bugs, open_browser, shortlinks,
               blacklist=blacklist, extended=extended,
               filename_save=filename_save,
               filename_compare=filename_compare,
               filename_postponed=filename_postponed)


def print_subscribed_bugs(lpname, expiration, date_range, open_browser,
                          shortlinks, blacklist, limit_subscribed, extended):
    """Print subscribed bugs - optionally mark those not touched in a while."""
    logging.info('')
    if expiration is None:
        logging.info('Bugs subscribed to %s', lpname)
        expire_start = None
        expire_end = None
        tags = ["-bot-stop-nagging", "-server-todo"]
    else:
        logging.info('Bugs subscribed to %s and not touched in %s days',
                     lpname, expiration['expire'])
        expire_start = (datetime.strptime(date_range['start'], '%Y-%m-%d')
                        - timedelta(days=expiration['expire']))
        expire_end = (datetime.strptime(date_range['end'], '%Y-%m-%d')
                      - timedelta(days=expiration['expire']))
        expire_start = expire_start.strftime('%Y-%m-%d')
        expire_end = expire_end.strftime('%Y-%m-%d')
        tags = ["-bot-stop-nagging"]

    bugs = create_bug_list(
        expire_start,
        expire_end,
        lpname, TEAMLPNAME, None,
        tags=tags,
        status=OPEN_BUG_STATUSES,
    )
    print_bugs(bugs, open_browser, shortlinks,
               blacklist=blacklist, limit_subscribed=limit_subscribed,
               oder_by_date=True, extended=extended)


def main(date_range=None, debug=False, open_browser=None,
         lpname=TEAMLPNAME, bugsubscriber=False, shortlinks=True,
         activitysubscribernames=None, expiration=None,
         show_no_triage=False, show_tagged=False, show_subscribed=False,
         limit_subscribed=None, blacklist=None, tags=None,
         extended=False,
         filename_save=None, filename_compare=None, filename_postponed=None):
    """Connect to Launchpad, get range of bugs, print 'em."""
    if tags is None:
        tags = ["server-todo"]
    launchpad = connect_launchpad()
    logging.basicConfig(stream=sys.stdout, format='%(message)s',
                        level=logging.DEBUG if debug else logging.INFO)
    if activitysubscribernames:
        activitysubscribers = (
            launchpad.people[activitysubscribernames].participants
        )
    else:
        activitysubscribers = []

    if show_tagged:
        print_tagged_bugs(lpname, None, None, open_browser['triage'],
                          shortlinks, blacklist, activitysubscribers,
                          tags, extended, filename_save, filename_compare,
                          filename_postponed)

    if show_subscribed:
        print_subscribed_bugs(lpname, None, None,
                              open_browser['triage'], shortlinks,
                              blacklist, limit_subscribed, extended)

    if show_no_triage:
        return

    report_current_backlog(lpname)
    date_range['start'], date_range['end'] = parse_dates(date_range['start'],
                                                         date_range['end'])

    # Need to display date range as inclusive
    inclusive_start = datetime.strptime(date_range['start'], '%Y-%m-%d')
    inclusive_end = (
        datetime.strptime(date_range['end'], '%Y-%m-%d') -
        timedelta(days=1)
    )
    pretty_start = inclusive_start.strftime('%Y-%m-%d (%A)')
    pretty_end = inclusive_end.strftime('%Y-%m-%d (%A)')
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

    # Exclude all workflow bugs dealing with packaging tasks (merges,
    # syncs, et al) since they're noisy, don't need triaging work, and
    # are already tracked by other processes.
    tags = [f"-{t}" for t in PACKAGING_TASK_TAGS]
    bugs = create_bug_list(
        date_range['start'], date_range['end'],
        lpname, bugsubscriber, activitysubscribers,
        tags=tags
    )
    print_bugs(bugs, open_browser['triage'], shortlinks, blacklist=blacklist,
               extended=extended)

    if expiration['show_expiration']:
        print_tagged_bugs(lpname, expiration, date_range, open_browser['exp'],
                          shortlinks, blacklist, activitysubscribers, tags,
                          extended)
        print_subscribed_bugs(lpname, expiration, date_range,
                              open_browser['exp'], shortlinks, blacklist,
                              None, extended)


def launch():
    """Parse arguments provided."""
    description = 'Triage Helper to deal with launchpad bugs.'
    epilog = '''
Flags as listed per bug:
'*': selected team is directly subscribed to the bug
'+': last bug activity was by the selected team
'U': Updated in the last --flag-recent days
'O': Not updated in the last --flag-old days
'N': New bug compared to --compare-tagged-bugs-to
'v': SRU - a release is tagged needing verfication
'V': SRU - a release is tagged verified

Release as listed per bug:
- d: devel release
- bfj...: initial of the release e.g. j = jammy
For each of those characters upper case indicates the task is closed
'''

    parser = argparse.ArgumentParser(
        prog='ustriage',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=description,
        epilog=epilog)
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
    parser.add_argument('-o', '--open', action='store_const',
                        const=1, default=0,
                        help='open reported bugs in web browser')
    parser.add_argument('-O', '--open-expire', action='store_const', const=1,
                        dest='openexp', default=0,
                        help='open expiring bugs in web browser')
    parser.add_argument('-n', '--lpname', default=TEAMLPNAME,
                        help='specify the launchpad name to search for'
                             ' (default "%s"). Show * flag if a bug is'
                             'directly subscribed by that team' % TEAMLPNAME)
    parser.add_argument('-b', '--bugsubscriber', action='store_true',
                        help=('filter name as bug subscriber (default would '
                              'be structural subscriber)'))
    parser.add_argument('--fullurls', default=False, action='store_true',
                        help='show full URLs instead of shortcuts')
    parser.add_argument('--activitysubscribers',
                        default='ubuntu-server-active-triagers',
                        help='Show + flag when last touched by this team')
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
                        help='Do not report about expiration of tagged and'
                             ' subscribed bugs')
    parser.add_argument('--expire-tagged',
                        default=60,
                        type=int,
                        dest='expire_tagged',
                        help='Days to consider tagged bugs expired if no'
                             ' update happened')
    parser.add_argument('--expire',
                        default=180,
                        type=int,
                        dest='expire',
                        help='Days to consider subscribed bugs expired if no'
                             ' update happened')
    parser.add_argument('--tag',
                        default=DEFAULTTAG,
                        dest='tag',
                        help='Tag that marks bugs (default "%s"). This will be'
                             ' used for tag-expiry as well as --show-tagged'
                             ' selection.' % DEFAULTTAG)
    parser.add_argument('-T', '--show-tagged',
                        default=False,
                        action='store_true',
                        dest='show_tagged',
                        help='Display an additional list of bugs that'
                             ' (--lpname or "%s") is directly subscribed to'
                             ' and are tagged by (--tag or "%s")'
                        % (TEAMLPNAME, DEFAULTTAG))
    parser.add_argument('-B', '--show-subscribed',
                        default=False,
                        action='store_true',
                        dest='show_subscribed',
                        help='Display an additional list of bugs that '
                             ' (--lpname or "%s") is directly subscribed to'
                        % TEAMLPNAME)
    parser.add_argument('-N', '--no-show-triage',
                        default=False,
                        action='store_true',
                        dest='show_no_triage',
                        help='Do not Display the default triage content'
                             ' (recent and expiring bugs).')
    parser.add_argument('--show-subscribed-max',
                        default=None,
                        type=int,
                        dest='limit_subscribed',
                        help='Limits the report of --show-subscribed to the'
                             ' top and bottom number of tasks')
    parser.add_argument('-E', '--extended-format',
                        default=False,
                        action='store_true',
                        dest='extended_format',
                        help='Do Display bugs in extended format which adds'
                             ' date-last-updated, importance and assignee')
    parser.add_argument('-F', '--flag-recent',
                        default=False,
                        type=int,
                        dest='age',
                        help='Show U flag for bugs touched more recently than '
                             'this many days (default: disabled in triage, %s '
                             'days in tag/subscription search)'
                             % FLAG_RECENT_AGE)
    parser.add_argument('--flag-old',
                        default=False,
                        type=int,
                        dest='old',
                        help='Show O flag for bugs not touched for this many '
                             'days (default: disabled in triage, %s days in'
                             ' tag/subscription search)' % FLAG_OLD_AGE)
    parser.add_argument('-S', '--save-tagged-bugs',
                        default=None,
                        dest='filename_save',
                        help='Save the list of reported tagged bugs to file')
    parser.add_argument('-C', '--compare-tagged-bugs-to',
                        default=None,
                        dest='filename_compare',
                        help='Compare the reported tagged bugs to file. Lists '
                        'bugs closed since then and shows N flag on new bugs')
    parser.add_argument('-P', '--postponed-bugs',
                        default=None,
                        dest='filename_postponed',
                        help='List of [bug, date] to consider postponed')

    args = parser.parse_args()

    open_browser = {'triage': args.open,
                    'exp': args.openexp}
    expiration = {'expire_tagged': args.expire_tagged,
                  'expire': args.expire,
                  'show_expiration': args.show_expiration}
    date_range = {'start': args.start_date,
                  'end': args.end_date}

    if args.age is False and (args.show_subscribed or args.show_tagged):
        args.age = FLAG_RECENT_AGE
    if args.age is not False:
        Task.AGE = datetime.now(timezone.utc) - timedelta(days=args.age)
    if args.old is False and (args.show_subscribed or args.show_tagged):
        args.old = FLAG_OLD_AGE
    if args.old is not False:
        Task.OLD = datetime.now(timezone.utc) - timedelta(days=args.old)

    main(date_range, args.debug, open_browser,
         args.lpname, args.bugsubscriber, not args.fullurls,
         args.activitysubscribers, expiration, args.show_no_triage,
         args.show_tagged, args.show_subscribed, args.limit_subscribed,
         blacklist=None if args.no_blacklist else PACKAGE_BLACKLIST,
         tags=[args.tag], extended=args.extended_format,
         filename_save=args.filename_save,
         filename_compare=args.filename_compare,
         filename_postponed=args.filename_postponed)


if __name__ == '__main__':
    launch()
