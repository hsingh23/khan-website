import sys
import re
import subprocess
import os
import optparse

sys.path.append(os.path.abspath("."))
import compress
from secrets import hipchat_deploy_token

import hipchat.room
import hipchat.config
hipchat.config.manual_init(hipchat_deploy_token)

def popen_results(args):
    proc = subprocess.Popen(args, stdout=subprocess.PIPE)
    return proc.communicate()[0]

def send_hipchat_deploy_message(version):
    url = "%s.%s.appspot.com" % (version, get_app_id())

    hg_id = hg_version()
    kiln_url = "https://khanacademy.kilnhg.com/Search?search=%s" % hg_id

    git_id = git_version()
    github_url = "https://github.com/Khan/khan-exercises/commit/%s" % git_id

    hipchat_message( \
            """Ooh ooh, ahh ahh.
            Deployed to <a href='http://%s'>%s</a>.
            website: <a href='%s'>version %s</a>,
            khan-exercises: <a href='%s'>version %s</a>""" % (url, url, kiln_url, hg_id, github_url, git_id))

def hipchat_message(msg):
    for room in hipchat.room.Room.list():

        if room.name in ('1s and 0s', 'Exercises'):

            result = ""
            msg_dict = {"room_id": room.room_id, "from": "Deploy Monkey", "message": msg, "color": "purple"}

            try:
                result = str(hipchat.room.Room.message(**msg_dict))
            except:
                pass

            if "sent" in result:
                print "Notified Hipchat room %s" % room.name
            else:
                print "Failed to send message to Hipchat: %s" % msg

def get_app_id():
    f = open("app.yaml", "r")
    contents = f.read()
    f.close()

    app_re = re.compile("^application:\s+(.+)$", re.MULTILINE)
    match = app_re.search(contents)

    return match.groups()[0]

def hg_st():
    output = popen_results(['hg', 'st', '-mard', '-S'])
    return len(output) > 0

def hg_pull_up():
    # Pull latest
    popen_results(['hg', 'pull'])

    # Hg up and make sure we didn't hit a merge
    output = popen_results(['hg', 'up'])
    lines = output.split("\n")
    if len(lines) != 2 or lines[0].find("files updated") < 0:
        # Ran into merge or other problem
        return -1

    return hg_version()

def hg_version():
    # grab the tip changeset hash
    pattern = re.compile("^changeset:\\s+\\d+:(.+)$")

    output = popen_results(['hg', 'tip'])
    lines = output.split("\n")
    for line in lines:
        match = pattern.match(line)
        if match:
            return match.groups()[0]

    return -1

def git_version():
    # grab the tip changeset hash
    return popen_results(['git', '--work-tree=khan-exercises/', '--git-dir=khan-exercises/.git', 'rev-parse', 'HEAD'])

def check_secrets():
    content = ""

    try:
        f = open("secrets.py", "r")
        content = f.read()
        f.close()
    except:
        return False

    # Try to find the beginning of our production facebook app secret
    # to verify deploy is being sent from correct directory.
    regex = re.compile("^facebook_app_secret = '050c.+'$", re.MULTILINE)
    return regex.search(content)

def compress_js():
    print "Compressing javascript"
    compress.compress_all_javascript()

def compress_css():
    print "Compressing stylesheets"
    compress.compress_all_stylesheets()

def deploy(version):
    print "Deploying version " + str(version)
    os.system("appcfg.py -V " + str(version) + " update .")

def main():

    parser = optparse.OptionParser()

    parser.add_option('-f', '--force',
        action="store_true", dest="force",
        help="Force deploy even with local changes", default=False)

    parser.add_option('-v', '--version',
        action="store", dest="version",
        help="Override the deployed version identifier", default="")

    parser.add_option('-x', '--no-up',
        action="store_true", dest="noup",
        help="Don't hg pull/up before deploy", default="")

    parser.add_option('-s', '--no-secrets',
        action="store_true", dest="nosecrets",
        help="Don't check for production secrets.py file before deploying", default="")

    parser.add_option('-d', '--dryrun',
        action="store_true", dest="dryrun",
        help="Dry run without the final deploy-to-App-Engine step", default=False)

    parser.add_option('-c', '--clean',
        action="store_true", dest="clean",
        help="Clean the old packages and generate them again", default=False)

    options, args = parser.parse_args()

    if not options.force:
        if hg_st():
            print "Local changes found in this directory, canceling deploy."
            return

    version = -1

    if not options.noup or len(options.version) == 0:
        version = hg_pull_up()
        if version <= 0:
            print "Could not find version after 'hg pull', 'hg up', 'hg tip'."
            return

    if not options.nosecrets:
        if not check_secrets():
            print "Stopping deploy. It doesn't look like you're deploying from a directory with the appropriate secrets.py."
            return

    if len(options.version) > 0:
        version = options.version

    if options.clean:
        compress.hashes = {}

    print "Deploying version " + str(version)
    compress.revert_js_css_hashes()
    compress_js()
    compress_css()

    if not options.dryrun:
        deploy(version)
        compress.revert_js_css_hashes()
    send_hipchat_deploy_message(version)

if __name__ == "__main__":
    main()
