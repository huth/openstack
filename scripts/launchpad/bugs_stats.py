#!/usr/bin/env/python
#
# Creates a HTML file which can be used as a dashboard for
# cleanup tasks of the bug management.
#

import datetime
import json
import os
import requests
import logging

from jinja2 import Environment, FileSystemLoader
from launchpadlib.launchpad import Launchpad

RECENT_ACTIVITY_IN_DAYS = 14

LOG_FORMAT="%(asctime)s - %(levelname)s - %(funcName)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_NAME = "nova"

ALL_STATES = ["New", "Incomplete", "Confirmed", "Won't Fix", "Opinion",
              "Invalid", "Fix Released"]

LOG = logging.getLogger(__name__)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


class StatSummary(object):
    
    def __init__(self, person_url, person_name):
        self.person_url = person_url.encode('ascii', 'replace')
        self.person_name = person_name.encode('ascii', 'replace')
        self.created_reports = []
        self.confirmed_reports = []
        self.rejected_reports = []
        self.resolved_reports = []
        self.inquired_reports = []

    def __eq__(self, other):
        return (isinstance(other, self.__class__) and
               self.person_url == other.person_url)

    def __cmp__(self,other):
        return cmp(self.person_name, other.person_name)

    def __repr__(self):
        return "<StatSummary: person=%s, created=%d, confirmed=%d, rejected=%d, resolved=%d, inquired=%d, sum=%d>" % \
            (self.person_name, self.created, self.confirmed, self.rejected, self.resolved, self.inquired, self.sum)

    @property
    def sum(self):
        return len(self.created_reports) + \
               len(self.confirmed_reports) + \
               len(self.rejected_reports) + \
               len(self.resolved_reports) + \
               len(self.inquired_reports)

def get_project_client():
    cache_dir = os.path.expanduser("~/.launchpadlib/cache/")
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir, 0o700)
    # see "Authenticated access for website integration" 
    # at https://help.launchpad.net/API/launchpadlib 
    # from launchpadlib.credentials import Credentials
    # credentials = Credentials("my website")
    # request_token_info = credentials.get_request_token(web_root="production")

    # NOTE(markus_z): We have to use "login_with" to get the bug activities.
    #                 An anonymous login will give us an empty result.
    #                 That's a bug from Launchpad. See bug:
    #                 https://bugs.launchpad.net/launchpad/+bug/1569225
    launchpad = Launchpad.login_with(PROJECT_NAME + '-bugs',
                                     'production',
                                     cache_dir)
    project = launchpad.projects[PROJECT_NAME]
    return project

def get_recent_actions():
    LOG.info("querying recent bug triage actions ...")
    project = get_project_client()
    bug_tasks = project.searchTasks(status=ALL_STATES,
                                    order_by='-date_last_updated',
                                    omit_duplicates=False)
    today = datetime.datetime.today()
    stats = {}
    
    def get_summary(person):
        link = "?? unknown ??"
        name = "?? unknown ??"
        if person:
            link = person.web_link.encode('ascii', 'replace')
            name = person.display_name.encode('ascii', 'replace')
        if not link in stats.keys():
            stats[link] = StatSummary(link, name)
        return stats[link]
    
    def is_created(bug_task, a):
        return (a.whatchanged =="bug" and a.message == "added bug" and \
                bug_task.date_created == bug_task.bug.date_created) or \
                a.whatchanged == "bug task added" and a.newvalue == "nova"
    
    def is_rejected(a):
        return a.newvalue in ["Invalid", "Opinion", "Won't Fix"]
    
    def is_new_confirmed(a, bug_task):
        return a.newvalue == 'Confirmed' and a.oldvalue == "New" and \
            a.person != bug_task.owner
    
    def is_trackable_status_change(a):
        return a.whatchanged == "nova: status" and \
               a.newvalue in ["Incomplete", "Confirmed", "Won't Fix", "Opinion", "Invalid", "Fix Released"]
    
    def is_infra(person):
        return person.web_link.encode('ascii', 'replace') == \
            "https://launchpad.net/~hudson-openstack"
    
    for bug_task in bug_tasks:
        diff = today - bug_task.bug.date_last_updated.replace(tzinfo=None)
        if diff.days > RECENT_ACTIVITY_IN_DAYS:
            break
    
        for a in bug_task.bug.activity:
            diff = today - a.datechanged.replace(tzinfo=None)
            if diff.days > RECENT_ACTIVITY_IN_DAYS:
                # ignore activities which are not recent
                continue

            person = a.person
            web_link = bug_task.web_link.encode('ascii', 'replace')

            if is_created(bug_task, a):
                get_summary(person).created_reports.append(web_link)
            elif is_trackable_status_change(a):
                if is_rejected(a):
                    get_summary(person).rejected_reports.append(web_link)
                elif is_new_confirmed(a, bug_task):
                    get_summary(person).confirmed_reports.append(web_link)
                elif a.newvalue == 'Fix Released':
                    if is_infra(person):
                        person = bug_task.assignee if bug_task.assignee else person
                    get_summary(person).resolved_reports.append(web_link)
                elif a.newvalue == "Incomplete" or \
                    a.whatchanged == "marked as duplicate":
                    get_summary(person).inquired_reports.append(web_link)
    
    LOG.info("queried recent bug triage actions.")
    return stats.values()


def create_html_dashboard():
    LOG.info("creating html dashboard...")
    d = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
    j2_env = Environment(loader=FileSystemLoader(THIS_DIR),
                         trim_blocks=True,
                         autoescape=True)
    template = "bugs_stats_template.html"
    rendered_html = j2_env.get_template(template).render(
        last_update=d,
        recent_days=RECENT_ACTIVITY_IN_DAYS,
        recent_actions=sorted(get_recent_actions()),
    )
    with open("bugs-stats.html", "wb") as fh:
        fh.write(rendered_html)
    LOG.info("created html dashboard")

if __name__ == '__main__':
    LOG.info("starting script...")
    create_html_dashboard()
    LOG.info("end script")