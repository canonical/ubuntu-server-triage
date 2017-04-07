# Ubuntu Server Triage
Output Ubuntu Server Launchpad bugs that for triage. The script is used by members of the Ubuntu Server team to determine what Launchpad bugs to review on a particular day or range of days. Giving us programmatic access to a set of bugs to look at. The older method was to look at [this page](https://bugs.launchpad.net/ubuntu/?field.searchtext=&orderby=-date_last_updated&search=Search&field.status%3Alist=NEW&field.status%3Alist=CONFIRMED&field.status%3Alist=TRIAGED&field.status%3Alist=INPROGRESS&field.status%3Alist=FIXCOMMITTED&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&field.status%3Alist=INCOMPLETE_WITHOUT_RESPONSE&assignee_option=any&field.assignee=&field.bug_reporter=&field.bug_commenter=&field.subscriber=&field.structural_subscriber=ubuntu-server&field.component-empty-marker=1&field.tag=&field.tags_combinator=ANY&field.status_upstream-empty-marker=1&field.has_cve.used=&field.omit_dupes.used=&field.omit_dupes=on&field.affects_me.used=&field.has_no_package.used=&field.has_patch.used=&field.has_branches.used=&field.has_branches=on&field.has_no_branches.used=&field.has_no_branches=on&field.has_blueprints.used=&field.has_blueprints=on&field.has_no_blueprints.used=&field.has_no_blueprints=on) and manually find all the bugs corresponding to a particular bug.

To obtain and run:
```
wget https://raw.githubusercontent.com/powersj/ubuntu-server-triage/master/ustriage.py
chmod +x ustriage.py 
# Running with no arguments will get previous day's bugs
./ustriage.py
```

## Dates
Dates must follow the format: `%Y-%m-%d` (e.g. 2016-11-30, 1999-05-22)

### Single Date Argument
If only one date is given then all the bugs on that one day will be found. For example, the following finds all bugs last modified on only the 10th of September:
```
./ustriage.py 2016-09-10
```

### Two Date Arguments
If two dates are given then all the bugs found on those days and between (fully inclusive) wil be found. For example, the following, finds all bugs last modified on the 10th, 11th, and 12th of September:
```
./ustriage.py 2016-09-10 2016-09-12
```

## Arguments
### Follow Bug Links
By default the script outputs links of the form "LP: #XXXXXX". Ubuntu's
default browser, gnome-terminal, makes these appear as hyperlinks
automatically, saving space and leaving more for the bug titles. If
instead you'd like full URLs, use `--fullurls`.

### Open Bugs in Browser
Quite commonly the triager wants to open all bugs in the browser, to read, review and manage them. Via ``open`` argument that can be done automatically.
```
./ustriage.py --open 2016-09-10 2016-09-12
```

### Launchpad Name and Subscription Type
By default this searches for the structural subscription of the ubuntu-server Team.
But depending on the use case one might overwrite the team name with `--lpname` (which can be any launchpad user, doesn't have to be a Team).
Additionally, especially when setting a personal name it is common that the filter should be switched to check for bug subscription instead of a structural subscription which can be done via `--bugsubscriber`.
```
show all bugs user paelzer is subscribed to (without date modification filter)
./ustriage.py --lpname paelzer --bugsubscriber

show all bugs user paelzer is subscribed to that were modified last month
./ustriage.py --lpname paelzer --bugsubscriber 2016-08-20 2016-09-20
```
