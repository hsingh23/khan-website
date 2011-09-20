import re
import cgi
import math
import os
import simplejson as json

from jinja2.utils import escape

from app import App
from templatefilters import seconds_to_time_string, slugify
from models import UserData, UserVideoCss
import consts
import util
import topics_list
import models
from api.auth import xsrf
import shared_jinja

from gae_bingo.gae_bingo import ab_test

def user_info(username, user_data):
    context = {"username": username, "user_data": user_data}
    return shared_jinja.get().render_template("user_info_only.html", **context)

def column_major_order_styles(num_cols=3, column_width=300, gutter=20, font_size=12):
    col_list = range(0, num_cols)
    link_height = font_size * 1.5

    return {
        "columns": col_list,
        "font_size": font_size,
        "link_height": link_height,
        "column_width": column_width,
        "column_width_plus_gutter": column_width + gutter,
    }

def column_major_sorted_videos(videos, num_cols=3, column_width=300, gutter=20, font_size=12):
    items_in_column = len(videos) / num_cols
    remainder = len(videos) % num_cols
    link_height = font_size * 1.5
    # Calculate the column indexes (tops of columns). Since video lists won't divide evenly, distribute
    # the remainder to the left-most columns first, and correctly increment the indices for remaining columns
    column_indices = [(items_in_column * multiplier + (multiplier if multiplier <= remainder else remainder)) for multiplier in range(1, num_cols + 1)]

    template_values = {
        "videos": videos,
        "column_width": column_width,
        "column_indices": column_indices,
        "link_height": link_height,
        "list_height": column_indices[0] * link_height,
    }

    return shared_jinja.get().render_template("column_major_order_videos.html", **template_values)

def flv_player_embed(video_path, width=800, height=480):
    return {
        "video_path": video_path, "width": width, "height": height
    }

def knowledgemap_embed(exercises, map_coords, admin=False):
    return {
        "App": App,
        "exercises": exercises,
        "map_coords": map_coords,
        'admin':json.dumps(admin)
    }

def exercise_icon(exercise, App):
    s_prefix = "node"
    if exercise.summative:
        s_prefix = "node-challenge"

    src = ""
    if exercise.review:
        src = "/images/node-review.png" # No reviews for summative exercises yet
    elif exercise.suggested:
        src = "/images/%s-suggested.png" % s_prefix
    elif exercise.proficient:
        src = "/images/%s-complete.png" % s_prefix
    else:
        src = "/images/%s-not-started.png" % s_prefix
    return {"src": src, "version": App.version}

def exercise_message(exercise, coaches, exercise_states):
    if exercise_states['endangered']:
        state = '_endangered'
    elif exercise_states['reviewing']:
        state = '_reviewing'
    elif exercise_states['proficient']:
        state = '_proficient'
        exercise_states.update({"heading": ab_test("proficiency_message_heading", ["Nice work!", "You're ready to move on!"])})
    elif exercise_states['struggling']:
        state = '_struggling'
        exercise_states['exercise_videos'] = exercise.related_videos_fetch()
    else:
        return None

    filename = "exercise_message%s.html" % state
    return shared_jinja.get().render_template(filename, **exercise_states)

def user_points(user_data):
    if user_data:
        points = user_data.points
    else:
        points = 0

    return {"points": points}

def possible_points_badge(points, possible_points, logged_in=True):
    return {
        "points": points,
        "possible_points": possible_points,
        "logged_in": logged_in
    }

def simple_student_info(user_data):
    member_for = seconds_to_time_string(util.seconds_since(user_data.joined), show_hours=False)
    return {
        "member_for": member_for
    }

def streak_bar(user_exercise):
    streak = user_exercise.streak
    longest_streak = 0

    if hasattr(user_exercise, "longest_streak"):
        longest_streak = user_exercise.longest_streak

    if hasattr(user_exercise, 'phantom') and user_exercise.phantom:
        streak = 0
        longest_streak = 0

    streak_max_width = 227
    required_streak = user_exercise.required_streak

    streak_width = min(streak_max_width, math.ceil((streak_max_width / float(required_streak)) * streak))
    longest_streak_width = min(streak_max_width, math.ceil((streak_max_width / float(required_streak)) * longest_streak))
    streak_icon_width = min(streak_max_width - 2, max(43, streak_width)) # 43 is width of streak icon

    width_required_for_label = 20
    show_streak_label = streak_width > width_required_for_label
    show_longest_streak_label = longest_streak_width > width_required_for_label and (longest_streak_width - streak_width) > width_required_for_label

    levels = []
    if user_exercise.summative:
        c_levels = required_streak / consts.REQUIRED_STREAK
        level_offset = streak_max_width / float(c_levels)
        for ix in range(c_levels - 1):
            levels.append(math.ceil((ix + 1) * level_offset) + 1)
    else:
        if streak > consts.MAX_STREAK_SHOWN:
            streak = "Max"

        if longest_streak > consts.MAX_STREAK_SHOWN:
            longest_streak = "Max"

    template_values = {
        "streak": streak,
        "longest_streak": longest_streak,
        "streak_width": streak_width,
        "longest_streak_width": longest_streak_width,
        "streak_max_width": streak_max_width,
        "streak_icon_width": streak_icon_width,
        "show_streak_label": show_streak_label,
        "show_longest_streak_label": show_longest_streak_label,
        "levels": levels
    }

    return shared_jinja.get().render_template("streak_bar.html", **template_values)

def reports_navigation(coach_email, current_report="classreport"):
    return {
        'coach_email': coach_email, 'current_report': current_report
    }

def playlist_browser(browser_id):
    template_values = {
        'browser_id': browser_id, 'playlist_structure': topics_list.PLAYLIST_STRUCTURE
    }

    return shared_jinja.get().render_template("playlist_browser.html", **template_values)

def playlist_browser_structure(structure, class_name="", level=0):
    if type(structure) == list:

        s = ""
        class_next = "topline"
        for sub_structure in structure:
            s += playlist_browser_structure(sub_structure, class_name=class_next, level=level)
            class_next = ""
        return s

    else:

        s = ""
        name = structure["name"]

        if structure.has_key("playlist"):

            playlist_title = structure["playlist"]
            href = "#%s" % escape(slugify(playlist_title))

            # We have two special case playlist URLs to worry about for now. Should remove later.
            if playlist_title.startswith("SAT"):
                href = "/sat"

            if level == 0:
                s += "<li class='solo'><a href='%s' class='menulink'>%s</a></li>" % (href, escape(name))
            else:
                s += "<li class='%s'><a href='%s'>%s</a></li>" % (class_name, href, escape(name))

        else:
            items = structure["items"]

            if level > 0:
                class_name += " sub"

            s += "<li class='%s'>%s <ul>%s</ul></li>" % (class_name, escape(name), playlist_browser_structure(items, level=level + 1))

        return s

def static_url(relative_url):
    return util.static_url(relative_url)

def empty_class_instructions(class_is_empty=True):
    user_data = UserData.current()
    coach_email = "Not signed in. Please sign in to see your Coach ID."
    if user_data:
        coach_email = user_data.email

    return {
        'App': App, 'class_is_empty': class_is_empty, 'coach_email': coach_email
    }

def crazyegg_tracker(enabled=True):
	return { 'enabled': enabled }

def xsrf_value():
    return xsrf.render_xsrf_js()

def video_name_and_progress(video):
    return "<span class='vid-progress v%d'>%s</span>" % (video.key().id(), escape(video.title.encode('utf-8', 'ignore')))

def user_video_css(user_data):
    if user_data:
        return "<link "\
                    "rel='stylesheet' "\
                    "type='text/css' "\
                    "href='/user_video_css?version=%d&id=%d'>"\
                "</link>" % (user_data.uservideocss_version, hash(user_data.user))
    else:
        return ''
