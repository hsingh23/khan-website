/**
 * Code to handle the logic for the profile page.
 */
// TODO: clean up all event listeners. This page does not remove any
// event listeners when tearing down the graphs.

var Profile = {
    version: 0,
    initialGraphUrl: null, // Filled in by the template after script load.
    email: null,  // Filled in by the template after script load.
    fLoadingGraph: false,
    fLoadedGraph: false,
    userGoalsHref: '',

    init: function() {
        Profile.render();
        $(".share-link").hide();
        $(".sharepop").hide();

        $(".achievement,.exercise,.video").hover(
            function () {
                $(this).find(".share-link").show();
                },
            function () {
                $(this).find(".share-link").hide();
                $(this).find(".sharepop").hide();
              });

        $(".share-link").click(function() {
            if ( $.browser.msie && (parseInt($.browser.version, 10) < 8) ) {
                $(this).next(".sharepop").toggle();
            } else {
                $(this).next(".sharepop").toggle(
                        "drop", { direction:"up" }, "fast" );
            }
            return false;
        });

        // Init Highcharts global options.
        Highcharts.setOptions({
            credits: {
                enabled: false
            },
            title: {
                text: ""
            },
            subtitle: {
                text: ""
            }
        });



        if ($.address){

            $.address.change(function(){
                Profile.historyChange();
            });

        }

        $(".graph-link").click(
            function(evt){
                evt.preventDefault();
                if($.address){
                    $.address.value( $( this ).attr( "href" ) )
                }
            }
        );

        $("#individual_report #achievements #achievement-list > ul").delegate("li", "click", function(e) {
            var category = $(this).attr("id");
            var clickedBadge = $(this);

            $("#badge-container").css("display", "");
            clickedBadge.siblings().removeClass("selected");

            if ($("#badge-container > #" + category ).is(":visible")) {
               if (clickedBadge.parents().hasClass("standard-view")) {
                   $("#badge-container > #" + category ).slideUp(300, function(){
                           $("#badge-container").css("display", "none");
                           clickedBadge.removeClass("selected");
                       });
               }
               else {
                   $("#badge-container > #" + category ).hide();
                   $("#badge-container").css("display", "none");
                   clickedBadge.removeClass("selected");
               }
            }
            else {
               var jelContainer = $("#badge-container");
               var oldHeight = jelContainer.height();
               $(jelContainer).children().hide();
               if (clickedBadge.parents().hasClass("standard-view")) {
                   $(jelContainer).css("min-height", oldHeight);
                   $("#" + category, jelContainer).slideDown(300, function() {
                       $(jelContainer).animate({"min-height": 0}, 200);
                   });
               } else {
                   $("#" + category, jelContainer).show();
               }
               clickedBadge.addClass("selected");
            }
        });

        // remove goals from IE<=8
        $(".lte8 .goals-accordion-content").remove();

        $("#stats-nav #nav-accordion")
            .accordion({
                header:".header",
                active:".graph-link-selected",
                autoHeight: false,
                clearStyle: true
            });

        setTimeout(function(){
            if (!Profile.fLoadingGraph && !Profile.fLoadedGraph)
            {
                // If 1000 millis after document.ready fires we still haven't
                // started loading a graph, load manually.
                // The externalChange trigger may have fired before we hooked
                // up a listener.
                Profile.historyChange();
            }
        }, 1000);

        Profile.ProgressSummaryView = new ProgressSummaryView();
    },
    highlightPoints: function(chart, fxnHighlight) {

        if (!chart) return;

        for (var ix = 0; ix < chart.series.length; ix++) {
            var series = chart.series[ix];

            this.muteSeriesStyles(series);

            for (var ixData = 0; ixData < series.data.length; ixData++) {
                var pointOptions = series.data[ixData].options;
                if (!pointOptions.marker) pointOptions.marker = {};
                pointOptions.marker.enabled = fxnHighlight(pointOptions);
                if (pointOptions.marker.enabled) pointOptions.marker.radius = 6;
            }

            series.isDirty = true;
        }

        chart.redraw();
    },

    muteSeriesStyles: function(series) {
        if (series.options.fMuted) return;

        series.graph.attr('opacity', 0.1);
        series.graph.attr('stroke', '#CCCCCC');
        series.options.lineWidth = 1;
        series.options.shadow = false;
        series.options.fMuted = true;
    },

    accentuateSeriesStyles: function(series) {
        series.options.lineWidth = 3.5;
        series.options.shadow = true;
        series.options.fMuted = false;
    },

    highlightSeries: function(chart, seriesHighlight) {

        if (!chart || !seriesHighlight) return;

        for (var ix = 0; ix < chart.series.length; ix++)
        {
            var series = chart.series[ix];
            var fSelected = (series == seriesHighlight);

            if (series.fSelectedLast == null || series.fSelectedLast != fSelected)
            {
                if (fSelected)
                    this.accentuateSeriesStyles(series);
                else
                    this.muteSeriesStyles(series);

                for (var ixData = 0; ixData < series.data.length; ixData++) {
                    series.data[ixData].options.marker = {
                        enabled: fSelected,
                        radius: fSelected ? 5 : 4
                    };
                }

                series.isDirty = true;
                series.fSelectedLast = fSelected;
            }
        }

        var options = seriesHighlight.options;
        options.color = '#0080C9';
        seriesHighlight.remove(false);
        chart.addSeries(options, false, false);

        chart.redraw();
    },

    collapseAccordion: function() {
        // Turn on collapsing, collapse everything, and turn off collapsing
        $("#stats-nav #nav-accordion").accordion(
                "option", "collapsible", true).accordion(
                    "activate", false).accordion(
                        "option", "collapsible", false);
    },

    baseGraphHref: function(href) {
        // regex for matching scheme:// part of uri
        // see http://tools.ietf.org/html/rfc3986#section-3.1
        var reScheme = /^\w[\w\d+-.]*:\/\//;
        var match = href.match(reScheme);
        if (match) {
            href = href.substring(match[0].length);
        }

        var ixSlash = href.indexOf("/");
        if (ixSlash > -1)
            href = href.substring(href.indexOf("/"));

        var ixQuestionMark = href.indexOf("?");
        if (ixQuestionMark > -1)
            href = href.substring(0, ixQuestionMark);

        return href;
    },

    /**
    * Expands the navigation accordion according to the link specified.
    * @return {boolean} whether or not a link was found to be a valid link.
    */
    expandAccordionForHref: function(href) {
        if (!href) {
            return false;
        }

        href = this.baseGraphHref(href).replace(/[<>']/g, "");

        var selectorAccordionSection =
                ".graph-link-header[href*='" + href + "']";

        if (!window.ClassProfile) {
            // TODO: Use reasonable styles
            var jel = $(selectorAccordionSection);
            if (!jel.length) {
                return false;
            }

            var index = jel.index(),
                isSubLink = jel.hasClass("graph-sub-link");

            if (!isSubLink) {
                $(".graph-link").css("background-color", "")
                    .eq(index).css("background-color", "#eee");

                $(".vital-statistics-description").hide()
                    .eq(index).show();
            }
            return true;
        }

        if ( $(selectorAccordionSection).length ) {
            $("#stats-nav #nav-accordion").accordion(
                "activate", selectorAccordionSection);
            return true;
        }
        this.collapseAccordion();
        return false;
    },

    styleSublinkFromHref: function(href) {

        if (!href) return;

        var reDtStart = /dt_start=[^&]+/;

        var matchStart = href.match(reDtStart);
        var sDtStart = matchStart ? matchStart[0] : "dt_start=lastweek";

        href = href.replace(/[<>']/g, "");

        $(".graph-sub-link").removeClass("graph-sub-link-selected");
        $(".graph-sub-link[href*='" + this.baseGraphHref(href) + "'][href*='" + sDtStart + "']")
            .addClass("graph-sub-link-selected");
    },

    // called whenever user clicks graph type accordion
    loadGraphFromLink: function(el) {
        if (!el) return;
        Profile.loadGraphStudentListAware(el.href);
    },

    loadGraphStudentListAware: function(url) {
        var $dropdown = $('#studentlists_dropdown ol');
        if ($dropdown.length == 1) {
            var list_id = $dropdown.data('selected').key;
            var qs = this.parseQueryString(url);
            qs['list_id'] = list_id;
            qs['version'] = Profile.version;
            qs['dt'] = $("#targetDatepicker").val();
            url = this.baseGraphHref(url) + '?' + this.reconstructQueryString(qs);
        }

        this.loadGraph(url);
    },

    loadFilters : function( href ){
        // fix the hrefs for each filter
        // console.log(href)

        var a = $("#stats-filters a[href^=\"" + href + "\"]").parent();
        $("#stats-filters .filter:visible").slideUp("slow");
        a.slideDown();
    },

    loadGraph: function(href, fNoHistoryEntry) {
        var apiCallbacksTable = {
            '/api/v1/user/exercises': this.renderExercisesTable,
            '/api/v1/user/students/goals': this.renderStudentGoals,
            '/api/v1/user/students/progressreport': window.ClassProfile ? ClassProfile.renderStudentProgressReport : null,
            '/api/v1/user/students/progress/summary': this.ProgressSummaryView.render
        };
        if (!href) return;

        if (this.fLoadingGraph) {
            setTimeout(function(){Profile.loadGraph(href);}, 200);
            return;
        }

        this.styleSublinkFromHref(href);
        this.fLoadingGraph = true;
        this.fLoadedGraph = true;

        var apiCallback = null;
        for (var uri in apiCallbacksTable) {
            if (href.indexOf(uri) > -1) {
                apiCallback = apiCallbacksTable[uri];
            }
        }
        $.ajax({
            type: "GET",
            url: Timezone.append_tz_offset_query_param(href),
            data: {},
            dataType: apiCallback ? 'json' : 'html',
            success: function(data){
                Profile.finishLoadGraph(data, href, fNoHistoryEntry, apiCallback);
            },
            error: function() {
                Profile.finishLoadGraphError();
            }
        });
        $("#graph-content").html("");
        this.showGraphThrobber(true);
    },

    finishLoadGraph: function(data, href, fNoHistoryEntry, apiCallback) {

        this.fLoadingGraph = false;

        if (!fNoHistoryEntry) {
            // Add history entry for browser
            //             if ($.address) {
            //                 $.address(href);
            // }
        }

        this.showGraphThrobber(false);
        this.styleSublinkFromHref(href);

        var start = (new Date).getTime();
        if (apiCallback) {
            apiCallback(data, href);
        } else {
            $("#graph-content").html(data);
        }
        var diff = (new Date).getTime() - start;
        KAConsole.log('API call rendered in ' + diff + ' ms.');
    },

    renderStudentGoals: function(data, href) {
        var studentGoalsViewModel = {
            rowData: [],
            sortDesc: '',
            filterDesc: ''
        };

        $.each(data, function(idx1, student) {
            student.goal_count = 0;
            student.most_recent_update = null;
            student.profile_url = "/profile?selected_graph_type=goals&student_email="+student.email;

            if (student.goals != undefined && student.goals.length > 0) {
                $.each(student.goals, function(idx2, goal) {
                    // Sort objectives by status
                    var progress_count = 0;
                    var found_struggling = false;

                    goal.objectiveWidth = 100/goal.objectives.length;
                    goal.objectives.sort(function(a,b) { return b.progress-a.progress; });

                    $.each(goal.objectives, function(idx3, objective) {
                        Goal.calcObjectiveDependents(objective, goal.objectiveWidth);

                        if (objective.status == 'proficient')
                            progress_count += 1000;
                        else if (objective.status == 'started' || objective.status == 'struggling')
                            progress_count += 1;

                        if (objective.status == 'struggling') {
                            found_struggling = true;
                            objective.struggling = true;
                        }
                        objective.statusCSS = objective.status ? objective.status : "not-started";

                        objective.objectiveID = idx3;
                    });

                    if (!student.most_recent_update || goal.updated > student.most_recent_update)
                        student.most_recent_update = goal;

                    student.goal_count++;
                    row = {
                        rowID: studentGoalsViewModel.rowData.length,
                        student: student,
                        goal: goal,
                        progress_count: progress_count,
                        goal_idx: student.goal_count,
                        struggling: found_struggling
                    };

                    $.each(goal.objectives, function(idx3, objective) {
                        objective.row = row;
                    });
                    studentGoalsViewModel.rowData.push(row);
                });
            } else {
                studentGoalsViewModel.rowData.push({
                    rowID: studentGoalsViewModel.rowData.length,
                    student: student,
                    goal: {objectives: []},
                    progress_count: -1,
                    goal_idx: 0,
                    struggling: false
                });
            }
        });

		var template = Templates.get( "profile.profile-class-goals" );
        $("#graph-content").html( template(studentGoalsViewModel) );

        $("#class-student-goal .goal-row").each(function() {
            var goalViewModel = studentGoalsViewModel.rowData[$(this).attr('data-id')];
            goalViewModel.rowElement = this;
            goalViewModel.countElement = $(this).find('.goal-count');
            goalViewModel.startTimeElement = $(this).find('.goal-start-time');
            goalViewModel.updateTimeElement = $(this).find('.goal-update-time');

            Profile.AddObjectiveHover($(this));

            $(this).find("a.objective").each(function() {
                var goalObjective = goalViewModel.goal.objectives[$(this).attr('data-id')];
                goalObjective.blockElement = this;

                if (goalObjective.type == 'GoalObjectiveExerciseProficiency') {
                    $(this).click(function() {
                        Profile.collapseAccordion();
                        Profile.loadGraph('/profile/graph/exerciseproblems?student_email='+goalViewModel.student.email+'&exercise_name='+goalObjective.internal_id);
                    });
                } else {
                    // Do something here for videos?
                }
            });
        });

        $("#student-goals-sort").change(function() { Profile.sortStudentGoals(studentGoalsViewModel); });

        $("input.student-goals-filter-check").change(function() { Profile.filterStudentGoals(studentGoalsViewModel); });
        $("#student-goals-search").keyup(function() { Profile.filterStudentGoals(studentGoalsViewModel); });

        Profile.sortStudentGoals(studentGoalsViewModel);
        Profile.filterStudentGoals(studentGoalsViewModel);
    },
    sortStudentGoals: function(studentGoalsViewModel) {
        var sort = $("#student-goals-sort").val();
        var show_updated = false;

        if (sort == 'name') {
            studentGoalsViewModel.rowData.sort(function(a,b) {
                if (b.student.nickname > a.student.nickname)
                    return -1;
                if (b.student.nickname < a.student.nickname)
                    return 1;
                return a.goal_idx-b.goal_idx;
            });

            studentGoalsViewModel.sortDesc = 'student name';
            show_updated = false; // started

        } else if (sort == 'progress') {
            studentGoalsViewModel.rowData.sort(function(a,b) {
                return b.progress_count - a.progress_count;
            });

            studentGoalsViewModel.sortDesc = 'goal progress';
            show_updated = true; // updated

        } else if (sort == 'created') {
            studentGoalsViewModel.rowData.sort(function(a,b) {
                if (a.goal && !b.goal)
                    return -1;
                if (b.goal && !a.goal)
                    return 1;
                if (a.goal && b.goal) {
                    if (b.goal.created > a.goal.created)
                        return 1;
                    if (b.goal.created < a.goal.created)
                        return -1;
                }
                return 0;
            });

            studentGoalsViewModel.sortDesc = 'goal creation time';
            show_updated = false; // started

        } else if (sort == 'updated') {
            studentGoalsViewModel.rowData.sort(function(a,b) {
                if (a.goal && !b.goal)
                    return -1;
                if (b.goal && !a.goal)
                    return 1;
                if (a.goal && b.goal) {
                    if (b.goal.updated > a.goal.updated)
                        return 1;
                    if (b.goal.updated < a.goal.updated)
                        return -1;
                }
                return 0;
            });

            studentGoalsViewModel.sortDesc = 'last work logged time';
            show_updated = true; // updated
        }

        var container = $('#class-student-goal').detach();
        $.each(studentGoalsViewModel.rowData, function(idx, row) {
            $(row.rowElement).detach();
            $(row.rowElement).appendTo(container);
            if (show_updated) {
                row.startTimeElement.hide();
                row.updateTimeElement.show();
            } else {
                row.startTimeElement.show();
                row.updateTimeElement.hide();
            }
        });
        container.insertAfter('#class-goal-filter-desc');

        Profile.updateStudentGoalsFilterText(studentGoalsViewModel);
    },
    updateStudentGoalsFilterText: function(studentGoalsViewModel) {
        var text = 'Sorted by ' + studentGoalsViewModel.sortDesc + '. ' + studentGoalsViewModel.filterDesc + '.';
        $('#class-goal-filter-desc').html(text);
    },
    filterStudentGoals: function(studentGoalsViewModel) {
        var filter_text = $.trim($("#student-goals-search").val().toLowerCase());
        var filters = {};
        $("input.student-goals-filter-check").each(function(idx, element) {
            filters[$(element).attr('name')] = $(element).is(":checked");
        });

        studentGoalsViewModel.filterDesc = '';
        if (filters['most-recent']) {
            studentGoalsViewModel.filterDesc += 'most recently worked on goals';
        }
        if (filters['in-progress']) {
            if (studentGoalsViewModel.filterDesc != '') studentGoalsViewModel.filterDesc += ', ';
            studentGoalsViewModel.filterDesc += 'goals in progress';
        }
        if (filters['struggling']) {
            if (studentGoalsViewModel.filterDesc != '') studentGoalsViewModel.filterDesc += ', ';
            studentGoalsViewModel.filterDesc += 'students who are struggling';
        }
        if (filter_text != '') {
            if (studentGoalsViewModel.filterDesc != '') studentGoalsViewModel.filterDesc += ', ';
            studentGoalsViewModel.filterDesc += 'students/goals matching "' + filter_text + '"';
        }
        if (studentGoalsViewModel.filterDesc != '')
            studentGoalsViewModel.filterDesc = 'Showing only ' + studentGoalsViewModel.filterDesc;
        else
            studentGoalsViewModel.filterDesc = 'No filters applied';

        var container = $('#class-student-goal').detach();

        $.each(studentGoalsViewModel.rowData, function(idx, row) {
            var row_visible = true;

            if (filters['most-recent']) {
                row_visible = row_visible && (!row.goal || (row.goal == row.student.most_recent_update));
            }
            if (filters['in-progress']) {
                row_visible = row_visible && (row.goal && (row.progress_count > 0));
            }
            if (filters['struggling']) {
                row_visible = row_visible && (row.struggling);
            }
            if (row_visible) {
                if (filter_text == '' || row.student.nickname.toLowerCase().indexOf(filter_text) >= 0) {
                    if (row.goal) {
                        $.each(row.goal.objectives, function(idx, objective) {
                            $(objective.blockElement).removeClass('matches-filter');
                        });
                    }
                } else {
                    row_visible = false;
                    if (row.goal) {
                        $.each(row.goal.objectives, function(idx, objective) {
                            if ((objective.description.toLowerCase().indexOf(filter_text) >= 0)) {
                                row_visible = true;
                                $(objective.blockElement).addClass('matches-filter');
                            } else {
                                $(objective.blockElement).removeClass('matches-filter');
                            }
                        });
                    }
                }
            }

            if (row_visible)
                $(row.rowElement).show();
            else
                $(row.rowElement).hide();

            if (filters['most-recent'])
                row.countElement.hide();
            else
                row.countElement.show();
        });

        container.insertAfter('#class-goal-filter-desc');

        Profile.updateStudentGoalsFilterText(studentGoalsViewModel);
    },

    finishLoadGraphError: function() {
        this.fLoadingGraph = false;
        this.showGraphThrobber(false);
        $("#graph-content").html("<div class='graph-notification'>It's our fault. We ran into a problem loading this graph. Try again later, and if this continues to happen please <a href='/reportissue?type=Defect'>let us know</a>.</div>");
    },

	/**
	 * Renders the exercise blocks given the JSON blob about the exercises.
	 */
	renderExercisesTable: function(data) {
		var templateContext = [];

		for ( var i = 0, exercise; exercise = data[i]; i++ ) {
			var stat = "Not started";
			var color = "";
			var states = exercise["exercise_states"];
			var totalDone = exercise["total_done"];

			if ( states["reviewing"] ) {
				stat = "Review";
				color = "review light";
			} else if ( states["proficient"] ) {
				// TODO: handle implicit proficiency - is that data in the API?
				// (due to proficiency in a more advanced module)
				stat = "Proficient";
				color = "proficient";
			} else if ( states["struggling"] ) {
				stat = "Struggling";
				color = "struggling";
			} else if ( totalDone > 0 ) {
				stat = "Started";
				color = "started";
			}

			if ( color ) {
				color = color + " action-gradient seethrough";
			} else {
				color = "transparent";
			}
			var model = exercise["exercise_model"];
			templateContext.push({
				"name": model["name"],
				"color": color,
				"status": stat,
				"shortName": model["short_display_name"] || model["display_name"],
				"displayName": model["display_name"],
				"progress": Math.floor( exercise["progress"] * 100 ) + "%",
				"totalDone": totalDone
			});
		}
		var template = Templates.get( "profile.exercise_progress" );
        $("#graph-content").html( template({ "exercises": templateContext }) );

		var infoHover = $("#info-hover-container");
		var lastHoverTime;
		var mouseX;
		var mouseY;
		$("#module-progress .student-module-status").hover(
			function(e) {
				var hoverTime = lastHoverTime = Date.now();
				mouseX = e.pageX;
				mouseY = e.pageY;
				var self = this;
				setTimeout(function() {
					if (hoverTime != lastHoverTime) {
						return;
					}

					var hoverData = $(self).children(".hover-data");
					if ($.trim(hoverData.html())) {
						infoHover.html($.trim(hoverData.html()));

						var left = mouseX + 15;
						var jelGraph = $("#graph-content");
						var leftMax = jelGraph.offset().left +
								jelGraph.width() - 150;

						infoHover.css('left', Math.min(left, leftMax));
						infoHover.css('top', mouseY + 5);
						infoHover.css('cursor', 'pointer');
						infoHover.css('position', 'fixed');
						infoHover.show();
					}
				}, 100);
			},
			function(e){
				lastHoverTime = null;
				$("#info-hover-container").hide();
			}
		);
		$("#module-progress .student-module-status").click(function(e) {
			$("#info-hover-container").hide();
			Profile.collapseAccordion();
			// Extract the name from the ID, which has been prefixed.
			var exerciseName = this.id.substring( "exercise-".length );
			Profile.loadGraph(
				"/profile/graph/exerciseproblems?" +
				"exercise_name=" + exerciseName + "&" +
				"student_email=" + Profile.email);
		});
	},

    // TODO: move history management out to a common utility
    historyChange: function(e) {
        var av = $.address ? $.address.value() : "/" ;
        // if(av === "/"){
        //     $.address.value(this.initialGraphUrl)
        // }
        var href = (av !== "/") ? av : this.initialGraphUrl;

        if ( href ) {
            // TODO: Fix this tab history action once and for ALL
            if (href === "/achievements") {
                $("#tab-achievements").click();
            } else if ( this.expandAccordionForHref(href) ) {
                this.loadGraph( href, true );
                this.loadFilters( href );
            } else {
                // Invalid URL - just try the first link available.
                var links = $(".graph-link");
                if ( links.length ) {
                    Profile.loadGraphFromLink( links[0] );
                }
            }
        }
    },

    showGraphThrobber: function(fVisible) {
        if (fVisible) {
            $("#graph-progress-bar").progressbar({value: 100}).slideDown("fast");
        } else {
            $("#graph-progress-bar").slideUp("fast", function() {
                $(this).hide();
            });
        }
    },

	// TODO: move this out to a more generic utility file.
    parseQueryString: function(url) {
        var qs = {};
        var parts = url.split('?');
        if(parts.length == 2) {
            var querystring = parts[1].split('&');
            for(var i = 0; i<querystring.length; i++) {
                var kv = querystring[i].split('=');
                if(kv[0].length > 0) { //fix trailing &
                    key = decodeURIComponent(kv[0]);
                    value = decodeURIComponent(kv[1]);
                    qs[key] = value;
                }
            }
        }
        return qs;
    },

	// TODO: move this out to a more generic utility file.
    reconstructQueryString: function(hash, kvjoin, eljoin) {
        kvjoin = kvjoin || '=';
        eljoin = eljoin || '&';
        qs = [];
        for(var key in hash) {
            if(hash.hasOwnProperty(key))
                qs.push(key + kvjoin + hash[key]);
        }
        return qs.join(eljoin);
    },

    AddObjectiveHover: function(element) {
        var infoHover = $("#info-hover-container");
        var lastHoverTime;
        var mouseX;
        var mouseY;
        element.find(".objective").hover(
            function(e) {
                var hoverTime = +(new Date);
                lastHoverTime = hoverTime;
                mouseX = e.pageX;
                mouseY = e.pageY;
                var self = this;
                setTimeout(function() {
                    if (hoverTime != lastHoverTime) {
                        return;
                    }

                    var hoverData = $(self).children(".hover-data");
                    if ($.trim(hoverData.html())) {
                        infoHover.html($.trim(hoverData.html()));

                        var left = mouseX + 15;
                        var jelGraph = $("#graph-content");
                        var leftMax = jelGraph.offset().left +
                                jelGraph.width() - 150;

                        infoHover.css('left', Math.min(left, leftMax));
                        infoHover.css('top', mouseY + 5);
                        infoHover.css('cursor', 'pointer');
						infoHover.css('position', 'fixed');
                        infoHover.show();
                    }
                }, 100);
            },
            function(e){
                lastHoverTime = null;
                $("#info-hover-container").hide();
            }
        );
    },
    render: function() {
        // TODO: This file is getting pretty long,
        // and I'd like to move each tab's JS out into a separate file

        if (window.ClassProfile) {
            return;
        }

        var profileTemplate = Templates.get("profile.profile");
        function createEncodedURLParameter(key, value) {
            return key + "=" + encodeURIComponent(value);
        }

        Handlebars.registerHelper("toLegacyGraphURL", function(type, student, coach, listId) {
            var url = "/profile/graph/" + type + "?",
                params = [];
            if (student) {
                params.push(createEncodedURLParameter("student_email", student));
            }

            if (coach) {
                params.push(createEncodedURLParameter("coach_email", coach));
            }

            if (listId) {
                params.push(createEncodedURLParameter("list_id", listId));
            }

            url += params.join("&");
            return url;
        });

        Handlebars.registerHelper("toAPIGraphURL", function(prefix, apiFunction, student, coach, listId) {
            var url = "/api/v1/" + prefix + "/" + apiFunction + "?",
                params = [];
            if (student) {
                params.push(createEncodedURLParameter("email", student));
            }

            if (coach) {
                params.push(createEncodedURLParameter("coach_email", coach));
            }

            if (listId) {
                params.push(createEncodedURLParameter("listId", listId));
            }

            url += params.join("&");
            return url;
        });

        // So that the date-picker can update the history param properly
        Handlebars.registerHelper("accordion-graph-date-picker-wrapper", function(block) {
            this.type = block.hash.type;
            return block(this);
        });

        Handlebars.registerPartial("accordion-graph-date-picker",
                Templates.get("profile.accordion-graph-date-picker"));
        Handlebars.registerPartial("vital-statistics", Templates.get("profile.vital-statistics"));

        $("#profile-content").html(profileTemplate(profileContext));
        $("abbr.timeago").timeago();
        $("#tabs").tabs().addClass('ui-tabs-vertical ui-helper-clearfix');
        $("#tabs li").removeClass('ui-corner-top').addClass('ui-corner-left');

        Profile.populateAchievements();
        Profile.populateGoals();

        // TODO: Might there be a better way
        // for server-side + client-side to co-exist in harmony?
        $("#tab-content-user-profile").append($("#server-side-recent-activity").html());
    },

    populateAchievements: function() {
        $.ajax({
            type: "GET",
            url: "/api/v1/user/badges",
            data: {"casing": "camel"},
            dataType: "json",
            success: function(data) {

                // TODO: save and cache these objects
                var fullBadgeList = new Badges.BadgeList(),
                    userBadgeList = new Badges.BadgeList();

                var collection = data["badgeCollections"];
                $.each(collection, function(i, categoryJson) {
                    $.each(categoryJson["badges"], function(j, json) {
                        fullBadgeList.add(new Badges.Badge(json));
                    });
                    $.each(categoryJson["userBadges"], function(j, json) {
                        userBadgeList.add(new Badges.Badge(json));
                    });
                });

                var displayCase = new Badges.DisplayCase({ model: userBadgeList });
                $(".sticker-book").append( displayCase.render().el );

                // TODO: make the rendering of the full badge page use the models above
                // and consolidate the information
                var badgeInfo = [
                        {
                            icon: "/images/badges/meteorite-medium.png",
                            className: "bronze",
                            label: "Meteorite"
                        },
                        {
                            icon: "/images/badges/moon-medium.png",
                            className: "silver",
                            label: "Moon"
                        },
                        {
                            icon: "/images/badges/earth-medium.png",
                            className: "gold",
                            label: "Earth"
                        },
                        {
                            icon: "/images/badges/sun-medium.png",
                            className: "diamond",
                            label: "Sun"
                        },
                        {
                            icon: "/images/badges/eclipse-medium.png",
                            className: "platinum",
                            label: "Black Hole"
                        },
                        {
                            icon: "/images/badges/master-challenge-blue.png",
                            className: "master",
                            label: "Challenge"
                        }
                    ];

                // Because we show the badges in reverse order,
                // from challenge/master/category-5 to meteorite/bronze/category-0
                Handlebars.registerHelper("reverseEach", function(context, block) {
                    var result = "";
                    for (var i = context.length - 1; i >= 0; i--) {
                        result += block(context[i]);
                    }
                    return result;
                });

                Handlebars.registerHelper("toMediumIconSrc", function(category) {
                    return badgeInfo[category].icon;
                });

                Handlebars.registerHelper("toBadgeClassName", function(category) {
                    return badgeInfo[category].className;
                });

                Handlebars.registerHelper("toBadgeLabel", function(category, fStandardView) {
                    var label = badgeInfo[category].label;

                    if (fStandardView) {
                        if (label === "Challenge") {
                            label += " Patches";
                        } else {
                            label += " Badges";
                        }
                    }
                    return label;
                });

                Handlebars.registerPartial(
                        "badge-container",
                        Templates.get("profile.badge-container"));
                Handlebars.registerPartial(
                        "badge",
                        Templates.get("profile.badge"));
                Handlebars.registerPartial(
                        "user-badge",
                        Templates.get("profile.user-badge"));

                $.each(data["badgeCollections"], function(collectionIndex, collection) {
                    $.each(collection["userBadges"], function(badgeIndex, badge) {
                        var targetContextNames = badge["targetContextNames"];
                        var numHidden = targetContextNames.length - 1
                        badge["visibleContextName"] = targetContextNames[0] || [];
                        badge["listContextNamesHidden"] = $.map(
                            targetContextNames.slice(1),
                            function(name, nameIndex) {
                                return {
                                    name: name,
                                    isLast: (nameIndex === numHidden - 1)
                                };
                            });
                        badge["hasMultiple"] = (badge["count"] > 1);
                    });
                });

                // TODO: what about mobile-view?
                data.fStandardView = true;

                var achievementsTemplate = Templates.get("profile.achievements");
                $("#tab-content-achievements").html(achievementsTemplate(data));

                $("#achievements #achievement-list > ul li").click(function() {
                     var category = $(this).attr('id');
                     var clickedBadge = $(this);

                     $("#badge-container").css("display", "");

                     clickedBadge.siblings().removeClass("selected");

                     if ($("#badge-container > #" + category ).is(":visible")) {
                        if (clickedBadge.parents().hasClass("standard-view")) {
                            $("#badge-container > #" + category ).slideUp(300, function(){
                                    $("#badge-container").css("display", "none");
                                    clickedBadge.removeClass("selected");
                                });
                        }
                        else {
                            $("#badge-container > #" + category ).hide();
                            $("#badge-container").css("display", "none");
                            clickedBadge.removeClass("selected");
                        }
                     }
                     else {
                        var jelContainer = $("#badge-container");
                        var oldHeight = jelContainer.height();
                        $(jelContainer).children().hide();
                        if (clickedBadge.parents().hasClass("standard-view")) {
                            $(jelContainer).css("min-height", oldHeight);
                            $("#" + category, jelContainer).slideDown(300, function() {
                                $(jelContainer).animate({"min-height": 0}, 200);
                            });
                        } else {
                            $("#" + category, jelContainer).show();
                        }
                        clickedBadge.addClass("selected");
                     }
                });
                $("abbr.timeago").timeago();
            }
        });
    },

    populateGoals: function() {
        // TODO: Need to support sending a different user's email,
        // as when a coach looks at a student's profile/goals.
        // Probably involves refactoring the Handlebars toAPIGraphURL helper
        $.ajax({
            type: "GET",
            url: "/api/v1/user/goals",
            dataType: "json",
            success: function(data) {
                GoalProfileViewsCollection.render(data, "/api/v1/user/goals?email=" + USER_EMAIL);
            }
        });
    }
};

$(function(){Profile.init();});
