import copy
import logging
from itertools import izip

from flask import request, current_app, Response

import datetime
import models
import layer_cache
import topics_list
import templatetags # Must be imported to register template tags
from badges import badges, util_badges, models_badges
from badges.templatetags import badge_notifications_html
from phantom_users.templatetags import login_notifications_html
from exercises import attempt_problem, make_wrong_attempt, UpdateExercise
from models import StudentList
from phantom_users.phantom_util import api_create_phantom
import notifications
from gae_bingo.gae_bingo import bingo
from autocomplete import video_title_dicts, playlist_title_dicts
from goals.models import GoalList, Goal, GoalObjective
import profiles.util_profile as util_profile
from profiles import class_progress_report_graph
from youtube_sync import youtube_get_video_data

from api import route
from api.decorators import jsonify, jsonp, compress, decompress, etag
from api.auth.decorators import oauth_required, oauth_optional, admin_required, developer_required
from api.auth.auth_util import unauthorized_response
from api.api_util import api_error_response, api_invalid_param_response, api_created_response, api_unauthorized_response

from google.appengine.ext import db

# add_action_results allows page-specific updatable info to be ferried along otherwise plain-jane responses
# case in point: /api/v1/user/videos/<youtube_id>/log which adds in user-specific video progress info to the
# response so that we can visibly award badges while the page silently posts log info in the background.
#
# If you're wondering how this happens, it's add_action_results has the side-effect of actually mutating
# the `obj` passed into it (but, i mean, that's what you want here)
#
# but you ask, what matter of client-side code actually takes care of doing that?
# have you seen javascript/shared-package/api.js ?
def add_action_results(obj, dict_results):

    badges_earned = []
    user_data = models.UserData.current()

    if user_data:
        dict_results["user_data"] = user_data

        dict_results["user_info_html"] = templatetags.user_info(user_data.nickname, user_data)

        user_notifications_dict = notifications.UserNotifier.pop_for_user_data(user_data)

        # Add any new badge notifications
        user_badges = user_notifications_dict["badges"]
        if len(user_badges) > 0:
            badges_dict = util_badges.all_badges_dict()

            for user_badge in user_badges:
                badge = badges_dict.get(user_badge.badge_name)

                if badge:
                    if not hasattr(badge, "user_badges"):
                        badge.user_badges = []

                    badge.user_badges.append(user_badge)
                    badge.is_owned = True
                    badges_earned.append(badge)

        if len(badges_earned) > 0:
            dict_results["badges_earned"] = badges_earned
            dict_results["badges_earned_html"] = badge_notifications_html(user_badges)

        # Add any new login notifications for phantom users
        login_notifications = user_notifications_dict["login"]
        if len(login_notifications) > 0:
            dict_results["login_notifications_html"] = login_notifications_html(login_notifications, user_data)

    obj.action_results = dict_results

@route("/api/v1/topicversion/<version>/content_topics", methods=["GET"])
@route("/api/v1/topicversion/<version>/playlists", methods=["GET"]) 
@route("/api/v1/content_topics", methods=["GET"])
@route("/api/v1/playlists", methods=["GET"]) # missing "url" and "youtube_id" properties that they had before
@jsonp
@layer_cache.cache_with_key_fxn(
    lambda version = None: "api_content_topics_%s_%s" % (version, models.TopicVersion.get_date_updated_by_id(version)),
    layer=layer_cache.Layers.Memcache)
@jsonify
def content_topics(version = None):
    version = models.TopicVersion.get_by_id(version)
    return models.Topic.get_content_topics(version)


@route("/api/v1/topicversion/<version>/topic/<topic_id>/videos", methods=["GET"])
@route("/api/v1/topicversion/<version>/playlists/<topic_id>/videos", methods=["GET"]) 
@route("/api/v1/topic/<topic_id>/videos", methods=["GET"])
@route("/api/v1/playlists/<topic_id>/videos", methods=["GET"])
@jsonp
@layer_cache.cache_with_key_fxn(
    lambda topic_id, version = None: "api_topic_videos_%s_%s_%s" % (topic_id, version, models.TopicVersion.get_date_updated_by_id(version)),
    layer=layer_cache.Layers.Memcache)
@jsonify
def topic_videos(topic_id, version = None):
    version = models.TopicVersion.get_by_id(version)
    topic = models.Topic.get_by_id(topic_id, version)
    if topic is None: 
        topic = models.Topic.get_by_title(topic_id, version) # needed for people who were using the playlists api
        if topic is None:
            raise ValueError("Invalid topic readable_id.")
    
    videos = models.Topic.get_cached_videos_for_topic(topic, False, version)
    for i, video in enumerate(videos):
        video.position = i + 1
    return videos

@route("/api/v1/topicversion/<version>/topic/<topic_id>/exercises", methods=["GET"])
@route("/api/v1/topicversion/<version>/playlists/<topic_id>/exercises", methods=["GET"]) 
@route("/api/v1/topic/<topic_id>/exercises", methods=["GET"])
@route("/api/v1/playlists/<topic_id>/exercises", methods=["GET"])
@jsonp
@layer_cache.cache_with_key_fxn(
    lambda topic_id, version = None: "api_topic_exercises_%s_%s_%s" % (topic_id, version, models.TopicVersion.get_date_updated_by_id(version)),
    layer=layer_cache.Layers.Memcache)
@jsonify
def topic_exercises(topic_id, version = None):
    version = models.TopicVersion.get_by_id(version)
    topic = models.Topic.get_by_id(topic_id, version)
    if topic is None: 
        topic = models.Topic.get_by_title(topic_id, version) # needed for people who were using the playlists api
        if topic is None:
            raise ValueError("Invalid topic readable_id.")
    
    exercises = topic.get_exercises()
    return exercises

@route("/api/v1/topicversion/<version>/topictree", methods=["GET"])
@route("/api/v1/topictree", methods=["GET"])
@etag(lambda: models.Setting.cached_library_content_date())
@jsonp
@decompress # too big even with compression ... need to add a datastore layer
@layer_cache.cache_with_key_fxn(
    lambda version = None: "api_topictree_%s_%s" % (version, models.TopicVersion.get_date_updated_by_id(version)),
    layer=layer_cache.Layers.Memcache)
@compress
@jsonify
def topictree(version = None):
    version = models.TopicVersion.get_by_id(version)
    return models.Topic.get_by_id("root", version).make_tree()

@route("/api/v1/topicversion/<version>/topic/<topic_id>", methods=["GET"])
@route("/api/v1/topic/<topic_id>", methods=["GET"])
@jsonp
@layer_cache.cache_with_key_fxn(
    lambda topic_id, version = None: "6api_topic_%s_%s_%s" % (topic_id, version, models.TopicVersion.get_date_updated_by_id(version)),
    layer=layer_cache.Layers.Memcache)
@jsonify
def topic(topic_id, version = None):
    logging.info("Not using cache")
    version = models.TopicVersion.get_by_id(version)
    topic = models.Topic.get_by_id(topic_id, version)

    if not topic:
        return api_invalid_param_response("Could not find topic with ID " + str(id))

    return topic.get_visible_data()

@route("/api/v1/topicversion/<version>/topic/<topic_id>", methods=["PUT"])    
@route("/api/v1/topic/<topic_id>", methods=["PUT"])
@oauth_optional()
@jsonp
@jsonify
def put_topic(topic_id, version = "edit"):
    version = models.TopicVersion.get_by_id(version)

    user_data = models.UserData.current()
    if not user_data:
        return api_invalid_param_response("User not logged in")

    topic_json = request.json
    logging.info(topic_json)

    topic = models.Topic.get_by_id(topic_id, version)

    if not topic:
        kwargs = dict((str(key), value) for key, value in topic_json.iteritems() if key in ['standalone_title', 'description', 'tags'])
        kwargs["version"]=version
        topic = models.Topic.insert(title = topic_json['title'], parent = None, **kwargs)
        # return api_invalid_param_response("Could not find topic with ID " + str(topic_id))
    else:
        changed = False
        kwargs = dict((str(key), value) for key, value in topic_json.iteritems() if key in ['id', 'title', 'standalone_title', 'description', 'tags', 'hide'])
        kwargs["version"]=version
        topic.update(**kwargs)

    return topic.get_visible_data()

@route("/api/v1/topicversion/<version>/topic/<parent_id>/addchild", methods=["POST"])   
@route("/api/v1/topic/<parent_id>/addchild", methods=["POST"])
@jsonp
@jsonify
def topic_add_child(parent_id, version = "edit"):
    version = models.TopicVersion.get_by_id(version)

    parent_topic = models.Topic.get_by_id(parent_id, version)
    if not parent_topic:
        return api_invalid_param_response("Could not find topic with ID " + str(parent_id))
    
    kind = request.request_string("kind")        
    id = request.request_string("id")

    if kind == "Topic":
        child =  models.Topic.get_by_id(id, version)
    elif kind == "Exercise":
        child = models.Exercise.get_by_name(id)
    elif kind == "Video":
        child = models.Video.get_for_readable_id(id)
    elif kind == "Url":
        child = models.Url.get_by_id(int(id))
    else:
        return api_invalid_param_response("Invalid kind to delete:" + kind)

    if not child:
        return api_invalid_param_response("Could not find a %s with ID %s " % (kind, id))

    pos = request.request_int("pos", default=0)

    parent_topic.add_child(child, pos)

    return parent_topic.get_visible_data()

@route("/api/v1/topicversion/<version>/topic/<parent_id>/deletechild", methods=["POST"])   
@route("/api/v1/topic/<parent_id>/deletechild", methods=["POST"])
@jsonp
@jsonify
def topic_delete_child(parent_id, version = "edit"):
    version = models.TopicVersion.get_by_id(version)

    parent_topic = models.Topic.get_by_id(parent_id, version)
    if not parent_topic:
        return api_invalid_param_response("Could not find topic with ID " + str(parent_id))
    
    kind = request.request_string("kind")        
    id = request.request_string("id")

    if kind == "Topic":
        child =  models.Topic.get_by_id(id, version)
    elif kind == "Exercise":
        child = models.Exercise.get_by_name(id)
    elif kind == "Video":
        child = models.Video.get_for_readable_id(id)
    elif kind == "Url":
        child = models.Url.get_by_id(int(id))
    else:
        return api_invalid_param_response("Invalid kind to delete:" + kind)

    if not child:
        return api_invalid_param_response("Could not find a %s with ID %s " % (kind, id))

    parent_topic.delete_child(child)

    return parent_topic.get_visible_data()
  
@route("/api/v1/topicversion/<version>/topic/<old_parent_id>/movechild", methods=["POST"])   
@route("/api/v1/topic/<old_parent_id>/movechild", methods=["POST"])
@jsonp
@jsonify
def topic_move_child(old_parent_id, version = "edit"):
    version = models.TopicVersion.get_by_id(version)

    old_parent_topic = models.Topic.get_by_id(old_parent_id, version)
    if not old_parent_topic:
        return api_invalid_param_response("Could not find topic with ID " + str(old_parent_id))
    
    kind = request.request_string("kind")        
    id = request.request_string("id")

    if kind == "Topic":
        child =  models.Topic.get_by_id(id, version)
    elif kind == "Exercise":
        child = models.Exercise.get_by_name(id)
    elif kind == "Video":
        child = models.Video.get_for_readable_id(id)
    elif kind == "Url":
        child = models.Url.get_by_id(int(id))
    else:
        return api_invalid_param_response("Invalid kind to move:" + kind)

    if not child:
        return api_invalid_param_response("Could not find a %s with ID %s " % (kind, id))

    new_parent_id = request.request_string("new_parent_id")
    new_parent =  models.Topic.get_by_id(new_parent_id, version)
    if not old_parent_topic:
        return api_invalid_param_response("Could not find topic with ID " + str(old_parent_id))
           
    new_parent_pos = request.request_string("new_parent_pos")

    old_parent_topic.move_child(child, new_parent, new_parent_pos)

    return True    

@route("/api/v1/topicversion/<version>/topic/<topic_id>/children", methods=["GET"])   
@route("/api/v1/topic/<topic_id>/children", methods=["GET"])
@jsonp
@layer_cache.cache_with_key_fxn(
    lambda topic_id, version = None: "api_topic_children_%s_%s_%s" % (topic_id, version, models.TopicVersion.get_date_updated_by_id(version)),
    layer=layer_cache.Layers.Memcache)
@jsonify
def topic_children(topic_id, version = None):
    version = models.TopicVersion.get_by_id(version)

    topic = models.Topic.get_by_id(topic_id, version)
    if topic is not None:
        return db.get(topic.child_keys)

@route("/api/v1/topicversion/<version>/setdefault", methods=["GET"])   
@jsonp
@jsonify
def topic_children(version = None):
    version = models.TopicVersion.get_by_id(version)
    version.set_default_version()
    models.TopicVersion.get_edit_version() # creates a new edit version if one does not already exists
    return version
    
@route("/api/v1/topicversion/<version>", methods=["GET"])   
@jsonp
@jsonify
def topic_version(version = None):
    version = models.TopicVersion.get_by_id(version)
    return version


@route("/api/v1/topicversions/", methods=["GET"])   
@jsonp
@jsonify
def topic_versions():
    version = models.TopicVersion.all().order("-number").fetch(10000)
    return version

@route("/api/v1/topicversion/<version>/unused_content", methods=["GET"])   
@jsonp
@jsonify
def topic_version_unused_content(version = None):
    version = models.TopicVersion.get_by_id(version)
    return version.get_unused_content()

@route("/api/v1/url/<int:url_id>", methods=["GET"])   
@jsonp
@jsonify
def get_url(url_id):
    return models.Url.get_by_id(url_id)

@route("/api/v1/url/", methods=["PUT"])   
@route("/api/v1/url/<int:url_id>", methods=["PUT"])   
@jsonp
@jsonify
def save_url(url_id = None):
    if url_id == None:
        url = models.Url()
        changed = True
    else:
        url = models.Url.get_by_id(url_id)
        if url is None:
            return api_invalid_param_response("Could not find a Url with ID %s " % (url_id))
        changed = False

    url_json = request.json
    for key, value in url_json.iteritems():
        if key in ["tags", "title", "url"]:
            if getattr(url, key) != value:
                setattr(url, key, value)
                changed = True

    if changed:
        url.put()
        models.Setting.cached_library_content_date(datetime.datetime.now())

    return url

@route("/api/v1/playlists/library", methods=["GET"])
@etag(lambda: models.Setting.cached_library_content_date())
@jsonp
@decompress # We compress and decompress around layer_cache so memcache never has any trouble storing the large amount of library data.
@layer_cache.cache_with_key_fxn(
    lambda: "api_library_%s" % models.Setting.cached_library_content_date(),
    layer=layer_cache.Layers.Memcache)
@compress
@jsonify
def playlists_library():
    playlists = fully_populated_playlists()

    playlist_dict = {}
    for playlist in playlists:
        playlist_dict[playlist.title] = playlist

    playlist_structure = copy.deepcopy(topics_list.PLAYLIST_STRUCTURE)
    replace_playlist_values(playlist_structure, playlist_dict)

    return playlist_structure

@route("/api/v1/playlists/library/list", methods=["GET"])
@jsonp
@decompress # We compress and decompress around layer_cache so memcache never has any trouble storing the large amount of library data.
@layer_cache.cache_with_key_fxn(
    lambda: "api_library_list_%s" % models.Setting.cached_library_content_date(),
    layer=layer_cache.Layers.Memcache)
@compress
@jsonify
def playlists_library_list():
    return fully_populated_playlists()

# We expose the following "fresh" route but don't publish the URL for internal services
# that don't want to deal w/ cached values.
@route("/api/v1/playlists/library/list/fresh", methods=["GET"])
@jsonp
@jsonify
def playlists_library_list_fresh():
    return fully_populated_playlists()

@route("/api/v1/exercises", methods=["GET"])
@jsonp
@jsonify
def get_exercises():
    return models.Exercise.get_all_use_cache()

@route("/api/v1/exercises/<exercise_name>", methods=["GET"])
@jsonp
@jsonify
def get_exercise(exercise_name):
    exercise = models.Exercise.get_by_name(exercise_name)
    if exercise:
        exercise_videos = exercise.related_videos_query()
        exercise.related_videos = map(lambda exercise_video: exercise_video.video.readable_id, exercise_videos)
    return exercise

@route("/api/v1/exercises_recent", methods=["GET"])
@jsonp
@jsonify
def exercise_recent_list():
    return models.Exercise.all().order('-creation_date').fetch(20)

@route("/api/v1/exercises/<exercise_name>/followup_exercises", methods=["GET"])
@jsonp
@jsonify
def exercise_info(exercise_name):
    exercise = models.Exercise.get_by_name(exercise_name)
    return exercise.followup_exercises() if exercise else []

@route("/api/v1/exercises/<exercise_name>/videos", methods=["GET"])
@jsonp
@jsonify
def exercise_videos(exercise_name):
    exercise = models.Exercise.get_by_name(exercise_name)
    if exercise:
        exercise_videos = exercise.related_videos_query()
        return map(lambda exercise_video: exercise_video.video, exercise_videos)
    return []

@route("/api/v1/exercises/<exercise_name>", methods=["PUT","POST"])
@developer_required
@jsonp
@jsonify
def exercise_save(exercise_name):
    request.json["name"] = exercise_name
    return UpdateExercise.do_update(request.json);

@route("/api/v1/videos/<video_id>", methods=["GET"])
@jsonp
@jsonify
def video(video_id):
    video = models.Video.get_for_readable_id(video_id)
    if video:
        return video
    return models.Video.all().filter("youtube_id =", video_id).get()

@route("/api/v1/videos_recent", methods=["GET"])
@jsonp
@jsonify
def video_recent_list():
    return models.Video.all().order('-date_added').fetch(20)

@route("/api/v1/videos/<video_id>/download_available", methods=["POST"])
@oauth_required(require_anointed_consumer=True)
@jsonp
@jsonify
def video_download_available(video_id):

    video = None
    formats = request.request_string("formats", default="")
    allowed_formats = ["mp4", "png"]

    # If for any crazy reason we happen to have multiple entities for a single youtube id,
    # make sure they all have the same downloadable_formats so we don't keep trying to export them.
    for video in models.Video.all().filter("youtube_id =", video_id):

        modified = False

        for downloadable_format in formats.split(","):
            if downloadable_format in allowed_formats and downloadable_format not in video.downloadable_formats:
                video.downloadable_formats.append(downloadable_format)
                modified = True

        if modified:
            video.put()

    return video

@route("/api/v1/videos/<video_id>/exercises", methods=["GET"])
@jsonp
@jsonify
def video_exercises(video_id):
    video = models.Video.all().filter("youtube_id =", video_id).get()
    if video:
        return video.related_exercises(bust_cache=True)
    return []

def fully_populated_playlists():
    playlists = models.Playlist.get_for_all_topics()
    video_key_dict = models.Video.get_dict(models.Video.all(), lambda video: video.key())

    video_playlist_query = models.VideoPlaylist.all()
    video_playlist_query.filter('live_association =', True)
    video_playlist_key_dict = models.VideoPlaylist.get_key_dict(video_playlist_query)

    for playlist in playlists:
        playlist.videos = []
        video_playlists = sorted(video_playlist_key_dict[playlist.key()].values(), key=lambda video_playlist: video_playlist.video_position)
        for video_playlist in video_playlists:
            video = video_key_dict[models.VideoPlaylist.video.get_value_for_datastore(video_playlist)]
            video.position = video_playlist.video_position
            playlist.videos.append(video)

    return playlists

@route("/api/v1/videos/youtubeinfo/<youtube_id>", methods=["GET"])
@developer_required
@jsonp
@jsonify
def get_youtube_info(youtube_id):
    video_data = models.Video(youtube_id=youtube_id)
    return youtube_get_video_data(video_data)

@route("/api/v1/videos/", methods=["POST","PUT"])
@route("/api/v1/videos/<video_id>", methods=["POST","PUT"])
@developer_required
@jsonp
@jsonify
def save_video(video_id=""):
    video_data = models.Video.get_for_readable_id(video_id)

    if not video_data:
        video_data = models.Video(youtube_id=request.json["youtube_id"])
        video_data = youtube_get_video_data(video_data)

    if video_data:
        if "readable_id" in request.json and request.json["readable_id"]:
            video_data.readable_id = request.json["readable_id"]

        if "title" in request.json and request.json["title"]:
            video_data.title = request.json["title"]

        if "youtube_id" in request.json and request.json["youtube_id"]:
            video_data.youtube_id = request.json["youtube_id"]

        if "description" in request.json and request.json["description"]:
            video_data.description = request.json["description"]

        if "keywords" in request.json and request.json["keywords"]:
            video_data.keywords = request.json["keywords"]

        video_data.put()
        models.Setting.cached_library_content_date(datetime.datetime.now())
        return video_data

    return None

def replace_playlist_values(structure, playlist_dict):
    if type(structure) == list:
        for sub_structure in structure:
            replace_playlist_values(sub_structure, playlist_dict)
    else:
        if "items" in structure:
            replace_playlist_values(structure["items"], playlist_dict)
        elif "playlist" in structure:
            # Replace string playlist title with real playlist object
            structure["playlist"] = playlist_dict[structure["playlist"]]

# Return specific user data requests from request
# IFF currently logged in user has permission to view
def get_visible_user_data_from_request(disable_coach_visibility=False,
                                       user_data=None):

    user_data = user_data or models.UserData.current()
    if not user_data:
        return None

    if request.request_string("email"):
        user_data_student = request.request_user_data("email")

        if user_data_student and user_data_student.user_email == user_data.user_email:
            # if email in request is that of the current user, simply return the
            # current user_data, no need to check permission to view
            return user_data

        if (user_data_student and
                (user_data.developer or
                        (not disable_coach_visibility and
                         user_data_student.is_coached_by(user_data)))):
            return user_data_student
        else:
            return None

    else:
        return user_data

@route("/api/v1/user", methods=["GET"])
@oauth_required()
@jsonp
@jsonify
def user_data_other():
    user_data = models.UserData.current()

    if user_data:
        user_data_student = get_visible_user_data_from_request()
        if user_data_student:
            return user_data_student

    return None

@route("/api/v1/user/students", methods=["GET"])
@oauth_required()
@jsonp
@jsonify
def user_data_student():
    user_data = models.UserData.current()

    if user_data:
        user_data_student = get_visible_user_data_from_request(disable_coach_visibility=True)
        if user_data_student:
            if request.request_string("list_id"):
                try:
                    student_list = util_profile.get_list(user_data_student, request)
                except Exception, e:
                    logging.error("%s: %s" % (request.url, e))
                    return None
                else:
                    return student_list.get_students_data()
            else:
                return user_data_student.get_students_data()

    return None

@route("/api/v1/user/studentlists", methods=["GET"])
@oauth_required()
@jsonp
@jsonify
def user_studentlists():
    user_data = models.UserData.current()

    if user_data:
        user_data_student = get_visible_user_data_from_request()
        if user_data_student:
            student_lists_model = StudentList.get_for_coach(user_data_student.key())
            student_lists = []
            for student_list in student_lists_model:
                student_lists.append({
                    'key': str(student_list.key()),
                    'name': student_list.name,
                })
            return student_lists

    return None

def filter_query_by_request_dates(query, property):

    if request.request_string("dt_start"):
        try:
            dt_start = request.request_date_iso("dt_start")
            query.filter("%s >=" % property, dt_start)
        except ValueError:
            raise ValueError("Invalid date format sent to dt_start, use ISO 8601 Combined.")

    if request.request_string("dt_end"):
        try:
            dt_end = request.request_date_iso("dt_end")
            query.filter("%s <" % property, dt_end)
        except ValueError:
            raise ValueError("Invalid date format sent to dt_end, use ISO 8601 Combined.")

@route("/api/v1/user/videos", methods=["GET"])
@oauth_required()
@jsonp
@jsonify
def user_videos_all():
    user_data = models.UserData.current()

    if user_data:
        user_data_student = get_visible_user_data_from_request()

        if user_data_student:
            user_videos_query = models.UserVideo.all().filter("user =", user_data_student.user)

            try:
                filter_query_by_request_dates(user_videos_query, "last_watched")
            except ValueError, e:
                return api_error_response(e)

            return user_videos_query.fetch(10000)

    return None

@route("/api/v1/user/videos/<youtube_id>", methods=["GET"])
@oauth_optional()
@jsonp
@jsonify
def user_videos_specific(youtube_id):
    user_data = models.UserData.current()

    if user_data and youtube_id:
        user_data_student = get_visible_user_data_from_request()
        video = models.Video.all().filter("youtube_id =", youtube_id).get()

        if user_data_student and video:
            user_videos = models.UserVideo.all().filter("user =", user_data_student.user).filter("video =", video)
            return user_videos.get()

    return None

# Can specify video using "video_key" parameter instead of youtube_id.
# Supports a GET request to solve the IE-behind-firewall issue with occasionally stripped POST data.
# See http://code.google.com/p/khanacademy/issues/detail?id=3098
# and http://stackoverflow.com/questions/328281/why-content-length-0-in-post-requests
@route("/api/v1/user/videos/<youtube_id>/log", methods=["POST"])
@route("/api/v1/user/videos/<youtube_id>/log_compatability", methods=["GET"])
@oauth_optional(require_anointed_consumer=True)
@api_create_phantom
@jsonp
@jsonify
def log_user_video(youtube_id):
    if (not request.request_string("seconds_watched") or
        not request.request_string("last_second_watched")):
        logging.critical("Video log request with no parameters received.")
        return api_invalid_param_response("Must supply seconds_watched and" +
            "last_second_watched")

    user_data = models.UserData.current()
    if not user_data:
        logging.warning("Video watched with no user_data present")
        return unauthorized_response()

    video_key_str = request.request_string("video_key")

    if not youtube_id and not video_key_str:
        return api_invalid_param_response("Must supply youtube_id or video_key")

    video_log = None
    if video_key_str:
        key = db.Key(video_key_str)
        video = db.get(key)
    else:
        video = models.Video.all().filter("youtube_id =", youtube_id).get()

    if not video:
        return api_error_response("Could not find video")

    seconds_watched = int(request.request_float("seconds_watched", default=0))
    last_second = int(request.request_float("last_second_watched", default=0))

    user_video, video_log, _, goals_updated = models.VideoLog.add_entry(
        user_data, video, seconds_watched, last_second)

    if video_log:
        action_results = {}
        action_results['user_video'] = user_video
        if goals_updated:
            action_results['updateGoals'] = [g.get_visible_data(None)
                for g in goals_updated]

        add_action_results(video_log, action_results)

    return video_log


@route("/api/v1/user/exercises", methods=["GET"])
@oauth_optional()
@jsonp
@jsonify
def user_exercises_all():
    """ Retrieves the list of exercise models wrapped inside of an object that
    gives information about what sorts of progress and interaction the current
    user has had with it.

    Defaults to a pre-phantom users, in which case the encasing object is
    skeletal and contains little information.

    """
    user_data = models.UserData.current()

    if not user_data:
        user_data = models.UserData.pre_phantom()
    student = get_visible_user_data_from_request(user_data=user_data)
    exercises = models.Exercise.get_all_use_cache()
    user_exercise_graph = models.UserExerciseGraph.get(student)
    if student.is_pre_phantom:
        user_exercises = []
    else:
        user_exercises = (models.UserExercise.all().
                          filter("user =", student.user).
                          fetch(10000))

    user_exercises_dict = dict((user_exercise.exercise, user_exercise)
                               for user_exercise in user_exercises)

    results = []
    for exercise in exercises:
        name = exercise.name
        if name not in user_exercises_dict:
            user_exercise = models.UserExercise()
            user_exercise.exercise = name
            user_exercise.user = student.user
        else:
            user_exercise = user_exercises_dict[name]
        user_exercise.exercise_model = exercise
        user_exercise._user_data = student
        user_exercise._user_exercise_graph = user_exercise_graph
        results.append(user_exercise)

    return results

@route("/api/v1/user/students/progress/summary", methods=["GET"])
@oauth_required()
@jsonp
@jsonify
def coach_progress_summary():
    user_data_coach = models.UserData.current()
    user_data_override = request.request_user_data("coach_email")
    if user_data_coach.developer and user_data_override:
        user_data_coach = user_data_override

    if request.request_string("list_id"):
        try:
            student_list = util_profile.get_list(user_data_coach, request)
        except Exception, e:
            logging.error("%s: %s" % (request.url, e))
            list_students = user_data_coach.get_students_data()
        else:
            list_students = student_list.get_students_data()
    else:
        list_students = user_data_coach.get_students_data()

    list_students = sorted(list_students, key=lambda student: student.nickname)
    user_exercise_graphs = models.UserExerciseGraph.get(list_students)

    student_review_exercise_names = []
    for user_exercise_graph in user_exercise_graphs:
        student_review_exercise_names.append(user_exercise_graph.review_exercise_names())

    exercises = models.Exercise.get_all_use_cache()
    exercise_data = []

    for exercise in exercises:
        progress_buckets = {
            'review': [],
            'proficient': [],
            'struggling': [],
            'started': [],
            'not-started': [],
        }

        for (student, user_exercise_graph, review_exercise_names) in izip(
                list_students, user_exercise_graphs,
                student_review_exercise_names):
            graph_dict = user_exercise_graph.graph_dict(exercise.name)

            if graph_dict['proficient']:
                if exercise.name in review_exercise_names:
                    status = 'review'
                else:
                    status = 'proficient'
            elif graph_dict['struggling']:
                status = 'struggling'
            elif graph_dict['total_done'] > 0:
                status = 'started'
            else:
                status = 'not-started'

            progress_buckets[status].append({
                    'nickname': student.nickname,
                    'email': student.email,
            })

        progress = [dict([('status', status),
                        ('students', progress_buckets[status])])
                        for status in progress_buckets]

        exercise_data.append({
            'name': exercise.name,
            'display_name': exercise.display_name,
            'progress': progress,
        })

    return {'exercises': exercise_data,
            'num_students': len(list_students)}

@route("/api/v1/user/exercises/<exercise_name>", methods=["GET"])
@oauth_optional()
@jsonp
@jsonify
def user_exercises_specific(exercise_name):
    user_data = models.UserData.current()

    if user_data and exercise_name:
        user_data_student = get_visible_user_data_from_request()
        exercise = models.Exercise.get_by_name(exercise_name)

        if user_data_student and exercise:
            user_exercise = models.UserExercise.all().filter("user =", user_data_student.user).filter("exercise =", exercise_name).get()

            if not user_exercise:
                user_exercise = models.UserExercise()
                user_exercise.exercise_model = exercise
                user_exercise.exercise = exercise_name
                user_exercise.user = user_data_student.user

            # Cheat and send back related videos when grabbing a single UserExercise for ease of exercise integration
            user_exercise.exercise_model.related_videos = map(lambda exercise_video: exercise_video.video, user_exercise.exercise_model.related_videos_fetch())
            return user_exercise

    return None

def user_followup_exercises(exercise_name):
    user_data = models.UserData.current()

    if user_data and exercise_name:

        user_data_student = get_visible_user_data_from_request()
        user_exercise_graph = models.UserExerciseGraph.get(user_data)

        user_exercises = models.UserExercise.all().filter("user =", user_data_student.user).fetch(10000)
        followup_exercises = models.Exercise.get_by_name(exercise_name).followup_exercises()

        followup_exercises_dict = dict((exercise.name, exercise) for exercise in followup_exercises)
        user_exercises_dict = dict((user_exercise.exercise, user_exercise) for user_exercise in user_exercises
                                                                            if user_exercise in followup_exercises)

        # create user_exercises that haven't been attempted yet
        for exercise_name in followup_exercises_dict:
            if not exercise_name in user_exercises_dict:
                user_exercise = models.UserExercise()
                user_exercise.exercise = exercise_name
                user_exercise.user = user_data_student.user
                user_exercises_dict[exercise_name] = user_exercise

        for exercise_name in user_exercises_dict:
            if exercise_name in followup_exercises_dict:
                user_exercises_dict[exercise_name].exercise_model = followup_exercises_dict[exercise_name]
                user_exercises_dict[exercise_name]._user_data = user_data_student
                user_exercises_dict[exercise_name]._user_exercise_graph = user_exercise_graph

        return user_exercises_dict.values()

    return None

@route("/api/v1/user/exercises/<exercise_name>/followup_exercises", methods=["GET"])
@oauth_optional()
@jsonp
@jsonify
def api_user_followups(exercise_name):
    return user_followup_exercises(exercise_name)

@route("/api/v1/user/playlists", methods=["GET"])
@oauth_required()
@jsonp
@jsonify
def user_playlists_all():
    user_data = models.UserData.current()

    if user_data:
        user_data_student = get_visible_user_data_from_request()

        if user_data_student:
            user_playlists = models.UserPlaylist.all().filter("user =", user_data_student.user)
            return user_playlists.fetch(10000)

    return None

@route("/api/v1/user/playlists/<playlist_title>", methods=["GET"])
@oauth_required()
@jsonp
@jsonify
def user_playlists_specific(playlist_title):
    user_data = models.UserData.current()

    if user_data and playlist_title:
        user_data_student = get_visible_user_data_from_request()
        playlist = models.Playlist.all().filter("title =", playlist_title).get()

        if user_data_student and playlist:
            user_playlists = models.UserPlaylist.all().filter("user =", user_data_student.user).filter("playlist =", playlist)
            return user_playlists.get()

    return None

@route("/api/v1/user/exercises/<exercise_name>/log", methods=["GET"])
@oauth_required()
@jsonp
@jsonify
def user_problem_logs(exercise_name):
    user_data = models.UserData.current()

    if user_data and exercise_name:
        user_data_student = get_visible_user_data_from_request()
        exercise = models.Exercise.get_by_name(exercise_name)

        if user_data_student and exercise:

            problem_log_query = models.ProblemLog.all()
            problem_log_query.filter("user =", user_data_student.user)
            problem_log_query.filter("exercise =", exercise.name)

            try:
                filter_query_by_request_dates(problem_log_query, "time_done")
            except ValueError, e:
                return api_error_response(e)

            problem_log_query.order("time_done")

            return problem_log_query.fetch(500)

    return None

@route("/api/v1/user/exercises/<exercise_name>/problems/<int:problem_number>/attempt", methods=["POST"])
@oauth_optional()
@api_create_phantom
@jsonp
@jsonify
def attempt_problem_number(exercise_name, problem_number):
    user_data = models.UserData.current()

    if user_data:
        exercise = models.Exercise.get_by_name(exercise_name)
        user_exercise = user_data.get_or_insert_exercise(exercise)

        if user_exercise and problem_number:

            user_exercise, user_exercise_graph, goals_updated = attempt_problem(
                    user_data,
                    user_exercise,
                    problem_number,
                    request.request_int("attempt_number"),
                    request.request_string("attempt_content"),
                    request.request_string("sha1"),
                    request.request_string("seed"),
                    request.request_bool("complete"),
                    request.request_int("count_hints", default=0),
                    int(request.request_float("time_taken")),
                    request.request_string("non_summative"),
                    request.request_string("problem_type"),
                    request.remote_addr,
                    )

            # this always returns a delta of points earned each attempt
            points_earned = user_data.points - user_data.original_points()
            if(user_exercise.streak == 0):
                # never award points for a zero streak
                points_earned = 0
            if(user_exercise.streak == 1):
                # award points for the first correct exercise done, even if no prior history exists
                # and the above pts-original points gives a wrong answer
                points_earned = user_data.points if (user_data.points == points_earned) else points_earned

            user_states = user_exercise_graph.states(exercise.name)

            action_results = {
                "exercise_state": {
                    "state": [state for state in user_states if user_states[state]],
                    "template": templatetags.exercise_message(exercise, user_data.coaches, user_states),
                },
                "points_earned": {"points": points_earned},
                "attempt_correct": request.request_bool("complete")
            }

            if goals_updated:
                action_results['updateGoals'] = [g.get_visible_data(None) for g in goals_updated]

            add_action_results(user_exercise, action_results)
            return user_exercise

    logging.warning("Problem %d attempted with no user_data present", problem_number)
    return unauthorized_response()

@route("/api/v1/user/exercises/<exercise_name>/problems/<int:problem_number>/hint", methods=["POST"])
@oauth_optional()
@api_create_phantom
@jsonp
@jsonify
def hint_problem_number(exercise_name, problem_number):

    user_data = models.UserData.current()

    if user_data:
        exercise = models.Exercise.get_by_name(exercise_name)
        user_exercise = user_data.get_or_insert_exercise(exercise)

        if user_exercise and problem_number:

            attempt_number = request.request_int("attempt_number")
            count_hints = request.request_int("count_hints")

            user_exercise, user_exercise_graph, goals_updated = attempt_problem(
                    user_data,
                    user_exercise,
                    problem_number,
                    attempt_number,
                    request.request_string("attempt_content"),
                    request.request_string("sha1"),
                    request.request_string("seed"),
                    request.request_bool("complete"),
                    count_hints,
                    int(request.request_float("time_taken")),
                    request.request_string("non_summative"),
                    request.request_string("problem_type"),
                    request.remote_addr,
                    )

            user_states = user_exercise_graph.states(exercise.name)
            add_action_results(user_exercise, {
                "exercise_message_html": templatetags.exercise_message(exercise, user_data.coaches, user_states),
                "exercise_state": {
                    "state": [state for state in user_states if user_states[state]],
                    "template": templatetags.exercise_message(exercise, user_data.coaches, user_states),
                }
            })

            # A hint will count against the user iff they haven't attempted the question yet and it's their first hint
            if attempt_number == 0 and count_hints == 1:
                bingo("hints_costly_hint")
                bingo("hints_costly_hint_binary")

            return user_exercise

    logging.warning("Problem %d attempted with no user_data present", problem_number)
    return unauthorized_response()

# TODO: Remove this route in v2
@route("/api/v1/user/exercises/<exercise_name>/reset_streak", methods=["POST"])
@oauth_optional()
@jsonp
@jsonify
def reset_problem_streak(exercise_name):
    return _attempt_problem_wrong(exercise_name)

@route("/api/v1/user/exercises/<exercise_name>/wrong_attempt", methods=["POST"])
@oauth_optional()
@jsonp
@jsonify
def attempt_problem_wrong(exercise_name):
    return _attempt_problem_wrong(exercise_name)

def _attempt_problem_wrong(exercise_name):
    user_data = models.UserData.current()

    if user_data and exercise_name:
        user_exercise = user_data.get_or_insert_exercise(models.Exercise.get_by_name(exercise_name))
        return make_wrong_attempt(user_data, user_exercise)

    return unauthorized_response()

@route("/api/v1/user/videos/<youtube_id>/log", methods=["GET"])
@oauth_required()
@jsonp
@jsonify
def user_video_logs(youtube_id):
    user_data = models.UserData.current()

    if user_data and youtube_id:
        user_data_student = get_visible_user_data_from_request()
        video = models.Video.all().filter("youtube_id =", youtube_id).get()

        if user_data_student and video:

            video_log_query = models.VideoLog.all()
            video_log_query.filter("user =", user_data_student.user)
            video_log_query.filter("video =", video)

            try:
                filter_query_by_request_dates(video_log_query, "time_watched")
            except ValueError, e:
                return api_error_response(e)

            video_log_query.order("time_watched")

            return video_log_query.fetch(500)

    return None

@route("/api/v1/badges", methods=["GET"])
@oauth_optional()
@jsonp
@jsonify
def badges_list():
    badges_dict = util_badges.all_badges_dict()

    user_data = models.UserData.current()
    if user_data:

        user_data_student = get_visible_user_data_from_request()
        if user_data_student:

            user_badges = models_badges.UserBadge.get_for(user_data_student)

            for user_badge in user_badges:

                badge = badges_dict.get(user_badge.badge_name)

                if badge:
                    if not hasattr(badge, "user_badges"):
                        badge.user_badges = []
                    badge.user_badges.append(user_badge)
                    badge.is_owned = True

    return sorted(filter(lambda badge: not badge.is_hidden(), badges_dict.values()), key=lambda badge: badge.name)

@route("/api/v1/badges/categories", methods=["GET"])
@jsonp
@jsonify
def badge_categories():
    return badges.BadgeCategory.all()

@route("/api/v1/badges/categories/<category>", methods=["GET"])
@jsonp
@jsonify
def badge_category(category):
    return filter(lambda badge_category: str(badge_category.category) == category, badges.BadgeCategory.all())

@route("/api/v1/developers/add", methods=["POST"])
@admin_required
@jsonp
@jsonify
def add_developer():
    user_data_developer = request.request_user_data("email")

    if not user_data_developer:
        return False

    user_data_developer.developer = True
    user_data_developer.put()

    return True

@route("/api/v1/developers/remove", methods=["POST"])
@admin_required
@jsonp
@jsonify
def remove_developer():
    user_data_developer = request.request_user_data("email")

    if not user_data_developer:
        return False

    user_data_developer.developer = False
    user_data_developer.put()

    return True

@route("/api/v1/coworkers/add", methods=["POST"])
@developer_required
@jsonp
@jsonify
def add_coworker():
    user_data_coach = request.request_user_data("coach_email")
    user_data_coworker = request.request_user_data("coworker_email")

    if user_data_coach and user_data_coworker:
        if not user_data_coworker.key_email in user_data_coach.coworkers:
            user_data_coach.coworkers.append(user_data_coworker.key_email)
            user_data_coach.put()

        if not user_data_coach.key_email in user_data_coworker.coworkers:
            user_data_coworker.coworkers.append(user_data_coach.key_email)
            user_data_coworker.put()

    return True

@route("/api/v1/coworkers/remove", methods=["POST"])
@developer_required
@jsonp
@jsonify
def remove_coworker():
    user_data_coach = request.request_user_data("coach_email")
    user_data_coworker = request.request_user_data("coworker_email")

    if user_data_coach and user_data_coworker:
        if user_data_coworker.key_email in user_data_coach.coworkers:
            user_data_coach.coworkers.remove(user_data_coworker.key_email)
            user_data_coach.put()

        if user_data_coach.key_email in user_data_coworker.coworkers:
            user_data_coworker.coworkers.remove(user_data_coach.key_email)
            user_data_coworker.put()

    return True

@route("/api/v1/autocomplete", methods=["GET"])
@jsonp
@jsonify
def autocomplete():

    video_results = []
    playlist_results = []

    query = request.request_string("q", default="").strip().lower()
    if query:

        max_results_per_type = 10

        exercise_results = filter(
                lambda exercise: query in exercise.display_name.lower(),
                models.Exercise.get_all_use_cache())
        video_results = filter(
                lambda video_dict: query in video_dict["title"].lower(),
                video_title_dicts())
        playlist_results = filter(
                lambda playlist_dict: query in playlist_dict["title"].lower(),
                playlist_title_dicts())

        exercise_results = sorted(
                exercise_results,
                key=lambda v: v.display_name.lower().index(query))[:max_results_per_type]
        video_results = sorted(
                video_results,
                key=lambda v: v["title"].lower().index(query))[:max_results_per_type]
        playlist_results = sorted(
                playlist_results,
                key=lambda p: p["title"].lower().index(query))[:max_results_per_type]

    return {
            "query": query,
            "videos": video_results,
            "playlists": playlist_results,
            "exercises": exercise_results
    }


@route("/api/v1/dev/problems", methods=["GET"])
@oauth_required()
@developer_required
@jsonp
@jsonify
def problem_logs():
    problem_log_query = models.ProblemLog.all()
    filter_query_by_request_dates(problem_log_query, "time_done")
    problem_log_query.order("time_done")
    return problem_log_query.fetch(request.request_int("max", default=500))

@route("/api/v1/dev/videos", methods=["GET"])
@oauth_required()
@developer_required
@jsonp
@jsonify
def video_logs():
    video_log_query = models.VideoLog.all()
    filter_query_by_request_dates(video_log_query, "time_watched")
    video_log_query.order("time_watched")
    return video_log_query.fetch(request.request_int("max", default=500))

@route("/api/v1/dev/users", methods=["GET"])
@oauth_required()
@developer_required
@jsonp
@jsonify
def user_data():
    user_data_query = models.UserData.all()
    filter_query_by_request_dates(user_data_query, "joined")
    user_data_query.order("joined")
    return user_data_query.fetch(request.request_int("max", default=500))

@route("/api/v1/user/students/progressreport", methods=["GET"])
@oauth_optional()
@jsonp
@jsonify
def get_student_progress_report():
    user_data_coach = models.UserData.current()

    user_data_override = request.request_user_data("coach_email")
    if user_data_coach and user_data_coach.developer and user_data_override:
        user_data_coach = user_data_override

    if not user_data_coach:
        return api_invalid_param_response("User is not logged in.")

    student_list = None

    student_list_key = request.request_string('list_id')
    if student_list_key and student_list_key != 'allstudents':
        student_lists = models.StudentList.get_for_coach(user_data_coach)
        for list in student_lists:
            if str(list.key()) == student_list_key:
                student_list = list
                break
        if not student_list:
            return api_invalid_param_response("Invalid list ID.")

    report_data = class_progress_report_graph.class_progress_report_graph_context(user_data_coach, student_list)

    return report_data

@route("/api/v1/user/goals", methods=["GET"])
@oauth_optional()
@jsonp
@jsonify
def get_user_goals():
    student = models.UserData.current() or models.UserData.pre_phantom()
    user_override = request.request_user_data("email")
    if user_override and user_override.key_email != student.key_email:
        if not user_override.is_visible_to(student):
            return api_unauthorized_response("Cannot view this profile")
        else:
            # Allow access to this student's profile
            student = user_override

    goals = GoalList.get_all_goals(student)
    return [g.get_visible_data() for g in goals]

@route("/api/v1/user/goals/current", methods=["GET"])
@oauth_optional()
@jsonp
@jsonify
def get_user_current_goals():
    student = models.UserData.current() or models.UserData.pre_phantom()

    user_override = request.request_user_data("email")
    if user_override and user_override.key_email != student.key_email:
        if not user_override.is_visible_to(student):
            return api_unauthorized_response("Cannot view this profile")
        else:
            # Allow access to this student's profile
            student = user_override

    goals = GoalList.get_current_goals(student)
    return [g.get_visible_data() for g in goals]

@route("/api/v1/user/students/goals", methods=["GET"])
@oauth_optional()
@jsonp
@jsonify
def get_student_goals():
    user_data_coach = request.request_user_data("coach_email")
    if not user_data_coach:
        return api_invalid_param_response("Coach not specified.")

    student_list = None

    # TomY TODO test/improve the performance of this

    student_list_key = request.request_string('list_id')
    if student_list_key and student_list_key != 'allstudents':
        student_lists = models.StudentList.get_for_coach(user_data_coach.key())
        for list in student_lists:
            if str(list.key()) == student_list_key:
                student_list = list
                break
        if not student_list:
            return api_invalid_param_response("Invalid list ID.")

    if student_list:
        students = student_list.get_students_data()
    else:
        students = user_data_coach.get_students_data()

    students = sorted(students, key=lambda student: student.nickname)
    user_exercise_graphs = models.UserExerciseGraph.get(students)

    return_data = []
    for student, uex_graph in izip(students, user_exercise_graphs):
        student_data = {}
        student_data['email'] = student.email
        student_data['nickname'] = student.nickname
        if student.has_current_goals:
            goals = GoalList.get_current_goals(student)
        else:
            goals = []
        student_data['goals'] = [g.get_visible_data(uex_graph) for g in goals]
        return_data.append(student_data)

    return return_data

@route("/api/v1/user/goals", methods=["POST"])
@oauth_optional()
@api_create_phantom
@jsonp
@jsonify
def create_user_goal():
    user_data = models.UserData.current()
    if not user_data:
        return api_invalid_param_response("User is not logged in.")

    user_override = request.request_user_data("email")
    if user_data.developer and user_override and user_override.key_email != user_data.key_email:
        user_data = user_override

    json = request.json
    title = json.get('title')
    if not title:
        return api_invalid_param_response('Title is invalid.')

    objective_descriptors = []

    goal_exercises = GoalList.exercises_in_current_goals(user_data)
    goal_videos = GoalList.videos_in_current_goals(user_data)

    if json:
        for obj in json['objectives']:
            if obj['type'] == 'GoalObjectiveAnyExerciseProficiency':
                objective_descriptors.append(obj)

            if obj['type'] == 'GoalObjectiveAnyVideo':
                objective_descriptors.append(obj)

            if obj['type'] == 'GoalObjectiveExerciseProficiency':
                obj['exercise'] = models.Exercise.get_by_name(obj['internal_id'])
                if not obj['exercise'] or not obj['exercise'].is_visible_to_current_user():
                    return api_invalid_param_response("Internal error: Could not find exercise.")
                if user_data.is_proficient_at(obj['exercise'].name):
                    return api_invalid_param_response("Exercise has already been completed.")
                if obj['exercise'].name in goal_exercises:
                    return api_invalid_param_response("Exercise is already an objective in a current goal.")
                objective_descriptors.append(obj)

            if obj['type'] == 'GoalObjectiveWatchVideo':
                obj['video'] = models.Video.get_for_readable_id(obj['internal_id'])
                if not obj['video']:
                    return api_invalid_param_response("Internal error: Could not find video.")
                user_video = models.UserVideo.get_for_video_and_user_data(obj['video'], user_data)
                if user_video and user_video.completed:
                    return api_invalid_param_response("Video has already been watched.")
                if obj['video'].readable_id in goal_videos:
                    return api_invalid_param_response("Video is already an objective in a current goal.")
                objective_descriptors.append(obj)

    if objective_descriptors:
        objectives = GoalObjective.from_descriptors(objective_descriptors,
            user_data)

        goal = Goal(parent=user_data, title=title, objectives=objectives)
        goal.put()
        user_data.ensure_has_current_goals()
        return goal.get_visible_data(None)
    else:
        return api_invalid_param_response("No objectives specified.")


@route("/api/v1/user/goals/<int:id>", methods=["GET"])
@oauth_optional()
@jsonp
@jsonify
def get_user_goal(id):
    user_data = models.UserData.current()
    if not user_data:
        return api_invalid_param_response("User not logged in")

    goal = Goal.get_by_id(id, parent=user_data)

    if not goal:
        return api_invalid_param_response("Could not find goal with ID " + str(id))

    return goal.get_visible_data(None)


@route("/api/v1/user/goals/<int:id>", methods=["PUT"])
@oauth_optional()
@jsonp
@jsonify
def put_user_goal(id):
    user_data = models.UserData.current()
    if not user_data:
        return api_invalid_param_response("User not logged in")

    goal = Goal.get_by_id(id, parent=user_data)

    if not goal:
        return api_invalid_param_response("Could not find goal with ID " + str(id))

    goal_json = request.json

    # currently all you can modify is the title
    if goal_json['title'] != goal.title:
        goal.title = goal_json['title']
        goal.put()

    # or abandon something
    if goal_json.get('abandoned') and not goal.abandoned:
        goal.abandon()
        goal.put()

    return goal.get_visible_data(None)


@route("/api/v1/user/goals/<int:id>", methods=["DELETE"])
@oauth_optional()
@jsonp
@jsonify
def delete_user_goal(id):
    user_data = models.UserData.current()
    if not user_data:
        return api_invalid_param_response("User not logged in")

    goal = Goal.get_by_id(id, parent=user_data)

    if not goal:
        return api_invalid_param_response("Could not find goal with ID " + str(id))

    goal.delete()

    return {}

@route("/api/v1/user/goals", methods=["DELETE"])
@oauth_optional()
@jsonp
@jsonify
def delete_user_goals():
    user_data = models.UserData.current()
    if not user_data.developer:
        return api_unauthorized_response("UNAUTHORIZED")

    user_override = request.request_user_data("email")
    if user_override and user_override.key_email != user_data.key_email:
        user_data = user_override

    GoalList.delete_all_goals(user_data)

    return "Goals deleted"
