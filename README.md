# Ubuntu Server Triage

[![Continuous Integration](https://github.com/canonical/ubuntu-server-triage/actions/workflows/ci.yaml/badge.svg)](https://github.com/canonical/ubuntu-server-triage/actions/workflows/ci.yaml)
[![ustriage](https://snapcraft.io/ustriage/badge.svg)](https://snapcraft.io/ustriage)

Output Ubuntu Server Launchpad bugs that for triage. The script is used by members of the Ubuntu Server team to determine what Launchpad bugs to review on a particular day or range of days. Giving us programmatic access to a set of bugs to look at. The older method was to look at [this page](https://bugs.launchpad.net/ubuntu/?field.searchtext=&orderby=-date_last_updated&search=Search&field.status%3Alist=NEW&field.status%3Alist=CONFIRMED&field.status%3Alist=TRIAGED&field.status%3Alist=INPROGRESS&field.status%3Alist=FIXCOMMITTED&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&field.status%3Alist=INCOMPLETE_WITHOUT_RESPONSE&assignee_option=any&field.assignee=&field.bug_reporter=&field.bug_commenter=&field.subscriber=&field.structural_subscriber=ubuntu-server&field.component-empty-marker=1&field.tag=&field.tags_combinator=ANY&field.status_upstream-empty-marker=1&field.has_cve.used=&field.omit_dupes.used=&field.omit_dupes=on&field.affects_me.used=&field.has_no_package.used=&field.has_patch.used=&field.has_branches.used=&field.has_branches=on&field.has_no_branches.used=&field.has_no_branches=on&field.has_blueprints.used=&field.has_blueprints=on&field.has_no_blueprints.used=&field.has_no_blueprints=on) and manually find all the bugs corresponding to a particular bug.

The easiest way to obtain the script and keep it updated is to use the snap:

```bash
sudo snap install ustriage
```

If using the snap is not possible, you can instead obtain it from git and run it by:

```bash
# Running with no arguments will get previous day's bugs
python -m ustriage
```

## Dates

Dates must follow the format: `%Y-%m-%d` (e.g. 2016-11-30, 1999-05-22)

### Single Date Argument

If only one date is given then all the bugs on that one day will be found. For example, the following finds all bugs last modified on only the 10th of September:

```bash
ustriage 2016-09-10
```

### Two Date Arguments

If two dates are given then all the bugs found on those days and between (fully inclusive) will be found. For example, the following, finds all bugs last modified on the 10th, 11th, and 12th of September:

```bash
ustriage 2016-09-10 2016-09-12
```

## Arguments

### Follow Bug Links

By default the script outputs links of the form "LP: #XXXXXX". Ubuntu's
default browser, gnome-terminal, makes these appear as hyperlinks
automatically, saving space and leaving more for the bug titles. If
instead you'd like full URLs, use `--fullurls`.

### Open Bugs in Browser

Quite commonly the triager wants to open all bugs in the browser, to read, review and manage them. Via ``open`` argument that can be done automatically.

```bash
ustriage --open 2016-09-10 2016-09-12
```

### Launchpad Name and Subscription Type

By default this searches for the structural subscription of the ubuntu-server Team.
But depending on the use case one might overwrite the team name with `--lpname` (which can be any launchpad user, doesn't have to be a Team).
Additionally, especially when setting a personal name it is common that the filter should be switched to check for bug subscription instead of a structural subscription which can be done via `--bugsubscriber`.

```bash
#  show all bugs user paelzer is subscribed to (without date modification filter)
ustriage --lpname paelzer --bugsubscriber

# show all bugs user paelzer is subscribed to that were modified last month
ustriage --lpname paelzer --bugsubscriber 2016-08-20 2016-09-20
```

## Bug expiration

To have some kind of tracking of the bugs subscribed by ubuntu-server as well as those tagged server-todo we have to make sure that we identify those that are dormant for too long.
Therefore by default bug expiration info is now added to the output by default.

Since these lists can be rather huge they are not opened in a browser by default.
But if wanted a user can set the option --open-expire

```bash
ustriage 2016-09-10 2016-09-12 --open-expire
```

If instead a user is not interested at all in the expiration he can disable the report by --no-expiration

```bash
ustriage 2016-09-10 2016-09-12 --no-expiration
```

### Output format

The default output format is tailored to a quick overview that also
can be copy and pasted into our triage status reports.

But if someone wants to get more insight from those lists the
argument --extended-format will add more fields to the output.
Those are "date of the last update", "importance" and "assignee" (if there is any)

### Further options and use cases of bug expiration

The expiration is defined as 60 days of inactivity in server-todo tagged bugs, and 180 days for the other ubuntu-server subscribed bugs.
These durations as well as the tag it considers for the "active" list can be tuned via the arguments, --expire-tagged, --expire and --tag.
This can be combined with a custom bug subscriber to be useful outside of the server team triage.
So the following example for example will list any bugs subscribed by hardcoredev which are inactive for 5 or more days with the tag super-urgent.

```bash
ustriage 2016-09-10 2016-09-12 --expire-tagged 5 --tag super-urgent --bugsubscriber hardcoredev
```

### Usage for server bug housekeeping

One can disable the default triage output via `--no-show-triage` and instead
request lists of tagged bugs `--show-tagged` or just subscribed `--show-subscribed`.
This is pretty handy on bug housekeeping as we use server-todo and subscription to
ubuntu-server as our current two levels of [bug tracking](https://github.com/canonical/ubuntu-maintainers-handbook/blob/main/BugTriage.md).

Thereby one can easily check all our current subscribed and `server-todo`
tagged bugs (or any other tag via `--tag`):

It turned out to be a common need to identify differences since the last
meeting. Since the situation in launchpad might have changed (dropped tag,
closed the bug, assigned to other teams, changed subscription) and not all of
them can be detected from launchpad-api after the fast ustriage now also
provides the option to save and compare a list of stored bugs.
On a usual run checking tagged bugs one can add -S to save the reported
bugs to a file. It is recommended to include the timestamp like:
`-S ~/savebugs/todo-$(date -I'seconds').yaml`

On later runs ustriage can compare the current set of bugs with any such stored
list and report new bugs (flag "N") and reports a list of cases gone from the
report.

Furthermore a common need is to see which bugs have had any updates recently.
The option `--flag-recent` allows to specify an amount of days (we use 6
usually) that will make a bug touched in that period get an updated flag "U"
in the report.

All that combined means that we usually run the following command for our
weekly checks

```bash
ustriage --no-show-triage --extended --show-tagged --flag-recent 6 -S ~/savebugs/todo-$(date -I'seconds').yaml -C ~/savebugs/todo-2022-02-01T12:45:10+01:00.yaml
```

Or our bigger backlog of any open `ubuntu-server` (or any other via --lpname)
subscribed bug task. This list can be rather long so `--show-subscribed-max`
reduces it to that many entries from top and bottom of the list.
This shows the most recent and the oldest 20 entries that are `ubuntu-server` subscribed.

```bash
ustriage --no-show-triage --show-subscribed --show-subscribed-max 20 --extended-format
```

Note: The file format on the save/compare feature isn't well defined, do
consider it experimental as it might change without warning. OTOH right now
being just a yaml list of bug numbers makes it very easy to - if needed - modify
it.
