/**
 * Views and logic for exercise/stack/card interactions
 * TODO(kamens): don't love the name "Exercises" for this namespace
 */
var Exercises = {

    exercise: null,
    userTopic: null,

    currentCard: null,
    currentCardView: null,

    incompleteStackCollection: null,
    incompleteStackView: null,

    completeStackCollection: null,
    completeStackView: null,

    /**
     * Called to initialize the exercise page. Passed in with JSON information
     * rendered from the server. See templates/exercises/power_template.html for details.
     */
    init: function(json) {

        this.exercise = json.exercise;

        // TODO(kamens): figure out the persistance model and hook 'er up
        // this.userTopicModel = new UserTopicModel(json.userTopic);
        this.userTopic = json.userTopic;

        this.incompleteStack = new Exercises.StackCollection(this.userTopic.incompleteStack); 
        this.completeStack = new Exercises.StackCollection(this.userTopic.completeStack); 

        // Start w/ the first card ready to go
        this.setCurrentCard(this.incompleteStack.pop());

        this.render();
    },

    render: function() {

        Handlebars.registerPartial("exercise-header", Templates.get("exercises.exercise-header"));
        Handlebars.registerPartial("card", Templates.get("exercises.card"));
        Handlebars.registerPartial("current-card-leaves", Templates.get("exercises.current-card-leaves"));
        Handlebars.registerPartial("problem-template", Templates.get("exercises.problem-template"));

        var profileExercise = Templates.get("exercises.exercise");

        $(".exercises-content-container").html(profileExercise({
            // TODO(kamens): Useful dict data here like crazzzyyyyyyyy
            exercise: this.exercise,
            userTopic: this.userTopic,
        }));

        this.incompleteStackView = new Exercises.StackView({
            collection: this.incompleteStack,
            el: $(".incomplete-stack"),
            frontVisible: false
        }); 

        this.completeStackView = new Exercises.StackView({
            collection: this.completeStack,
            el: $(".complete-stack"),
            frontVisible: true
        }); 

        this.currentCardView = new Exercises.CurrentCardView({
            model: this.currentCard,
            el: $(".current-card") }
        );

        this.currentCardView.render();
        this.incompleteStackView.render();
        this.completeStackView.render();

        this.listenForEvents();

    },

    listenForEvents: function() {

        // Triggered when Next Question has been clicked.
        //
        // Flip to the next card every time a new problem is generated by
        // khan-exercises
        //
        // TODO: eventually this event trigger should be owned by this object
        // instead of khan-exercises so we have better control of when to
        // render the results of khan-exercises or, alternatively, other
        // content inside of each card.
        $(Khan).bind("gotoNextProblem", function() {

            // Start the next card process
            Exercises.nextCard();

            // Return false so we take control of when nextProblem is triggered
            return false;

        });

        // Triggered when a problem is done (answered) but before Next Question
        // has been clicked
        $(Khan).bind("problemDone", function() {

            if (Exercises.currentCard) {

                // TODO(kamens): distinguish b/w leaves 3, 4, and 5
                Exercises.currentCard.set({leavesAvailable: 3});

                // Current card is done, lock in available leaves
                Exercises.currentCard.set({
                    done: true, 
                    leavesEarned: Exercises.currentCard.get("leavesAvailable")
                });

            }

        });

        $(Khan).bind("hintUsed", function() {
            // Using a hint drops leaves possibility to 2.
            if (Exercises.currentCard) {
                Exercises.currentCard.set({leavesAvailable: 2});
            }
        });

        $(Khan).bind("allHintsUsed", function() {
            // Using all hints drops leaves possibility to 1.
            if (Exercises.currentCard) {
                Exercises.currentCard.set({leavesAvailable: 1});
            }
        });

        // At the end of the stack we show the user all sorts of goodies
        this.incompleteStack.bind("stackComplete", function() { Exercises.endOfStack(); });

    },

    setCurrentCard: function(currentCard) {
        this.currentCard = currentCard;

        if (this.currentCardView) {
            this.currentCardView.setModel(this.currentCard);
        }
    },

    nextCard: function() {

        // animationOptions.deferreds stores all pending animations
        // that each subsequent step can wait on via $.when if needed
        var animationOptions = { deferreds: [] };

        if (this.currentCard) {

            // Move current to complete
            this.completeStack.add(this.currentCard, animationOptions);

            // Empty current card
            this.setCurrentCard(null);

            animationOptions.deferreds.push(this.currentCardView.animateToRight());

        }

        if (!this.currentCard && this.incompleteStack.length === 0) {

            // Stack's done and no card left!
            this.incompleteStack.trigger("stackComplete");

        }
        else {

            // Wait for push-to-right animations to finish
            $.when.apply(null, animationOptions.deferreds).done(function() {

                $(Khan).trigger("renderNextProblem");

                // Pop from left
                Exercises.setCurrentCard(Exercises.incompleteStack.pop(animationOptions));

                // Finish animating from left
                $.when(Exercises.currentCardView.moveLeft()).done(function() {

                    setTimeout(function() {
                        Exercises.currentCardView.animateFromLeft();
                    }, 1);

                });

            });

        }

    },

    endOfStack: function() {

        // TODO(kamens): something else.
        KAConsole.debugEnabled = true;
        KAConsole.log("Ended the stack!");

    }

};

/**
 * Model of any (current or in-stack) card
 */
Exercises.Card = Backbone.Model.extend({

    set: function(attributes, options) {

        // Once it's been set, leavesAvailable can only go down.
        if (attributes["leavesAvailable"]) {

            var currentLeaves = this.get("leavesAvailable");
            if (currentLeaves) {
                attributes["leavesAvailable"] = Math.min(currentLeaves, attributes["leavesAvailable"]);
            }

        }

        return Backbone.Model.prototype.set.call(this, attributes, options);

    }

});

/**
 * Collection model of a stack of cards
 */
Exercises.StackCollection = Backbone.Collection.extend({

    model: Exercises.Card,

    peek: function() {
        return _.head(this.models);
    },

    pop: function(animationOptions) {
        var head = this.peek();
        this.remove(head, animationOptions);
        return head;
    }

});

/**
 * View of a stack of cards
 */
Exercises.StackView = Backbone.View.extend({

    template: Templates.get("exercises.stack"),

    initialize: function() {

        var self = this;

        // deferAnimation is a wrapper function used to insert
        // any animations returned by fxn onto animationOption's
        // list of deferreds. This lets you chain complex
        // animations (see Exercises.nextCard).
        var deferAnimation = function(fxn) {
            return function(model, collection, options) {
                var result = fxn(model, collection, options);

                if (options && options.deferreds) {
                    options.deferreds.push(result);
                }

                return result;
            }
        };

        this.collection
            .bind("add", deferAnimation(function(card) {
                return self.animatePush(card);
            }))
            .bind("remove", deferAnimation(function() {
                return self.animatePop();
            }));

    },

    render: function() {

        var self = this;

        var collectionContext = _.map(this.collection.models, function(card, index) {
            return self.cardViewContext(card, index);
        });

        this.el.html(this.template({cards: collectionContext}));

        return this;

    },

    cardViewContext: function(card, index) {
        return _.extend(card.toJSON(), {index: index, frontVisible: this.options.frontVisible});
    },

    /**
     * Animate popping card off of stack
     */
    animatePop: function() {

        return this.el
            .find(".card-container")
                .first()
                    .slideUp(140, function() { $(this).remove(); });

    },

    /**
     * Animate pushing card onto head of stack
     */
    animatePush: function(card) {

        var context = this.cardViewContext(card, this.collection.length);

        return this.el
            .find(".stack")
                .prepend(
                    $(Templates.get("exercises.card")(context))
                        .css("display", "none")
                )
                .find(".card-container")
                    .first()
                        .delay(40)
                        .slideDown(140);

    }

});

/**
 * View of the single, currently-visible card
 */
Exercises.CurrentCardView = Backbone.View.extend({

    template: Templates.get("exercises.current-card"),

    model: null,

    initialize: function() {
        this.setModel(this.model);
    },

    /**
     * Update the view's model and reconnect events appropriately.
     * The current card view doesn't get completely re-initialized/rendered
     * when its model changes right now due to its reliance on khan-exercises
     * for rendering.
     */
    setModel: function(model) {

        var self = this;
        var leafEvents = ["change:done", "change:leavesEarned", "change:leavesAvailable"];

        if (this.model) {
            _.each(leafEvents, function(leafEvent) { self.model.unbind(leafEvent); });
        }

        if (model) {
            this.model = model;

            _.each(leafEvents, function(leafEvent) {
                self.model.bind(leafEvent, function() { self.updateLeaves(); });
            });

            this.updateLeaves();
        }

    },

    render: function(ix) {
        this.el.html(this.template(this.model.toJSON()));
        return this;
    },

    /**
     * Update the currently available or earned leaves in current card's view
     */
    updateLeaves: function() {
        this.el
            .find(".leaves-container")
                .html(
                    $(Templates.get("exercises.current-card-leaves")(this.model.toJSON()))
                ) 
    },

    /**
     * Animate current card to right-hand completed stack
     */
    animateToRight: function() {
        this.el.addClass("shrinkRight");

        // These animation fxns explicitly return null as they are used in deferreds
        // and may one day have deferrable animations (CSS3 animations aren't
        // deferred-friendly).
        return null;
    },

    /**
     * Animate card from left-hand completed stack to current card
     */
    animateFromLeft: function() {
        this.el
            .removeClass("notransition")
            .removeClass("shrinkLeft");

        // These animation fxns explicitly return null as they are used in deferreds
        // and may one day have deferrable animations (CSS3 animations aren't
        // deferred-friendly).
        return null;
    },

    /**
     * Move (unanimated) current card from right-hand stack to left-hand stack between
     * toRight/fromLeft animations
     */
    moveLeft: function() {
        this.el
            .addClass("notransition")
            .removeClass("shrinkRight")
            .addClass("shrinkLeft");

        // These animation fxns explicitly return null as they are used in deferreds
        // and may one day have deferrable animations (CSS3 animations aren't
        // deferred-friendly).
        return null;
    }

});
