/**
 * LocalStore is a *super* simple abstraction around localStorage for easy
 * get/set/delete. We may end up wanting something more powerful like
 * BankersBox, but for now this is much lighter weight.
 *
 * TODO(kamens): extremely unit-test-friendly.
 */
var LocalStore = {

    keyPrefix: "ka",

    cacheKey: function(key) {
        if (!key) {
            throw "Attempting to use LocalStore without a key"
        }

        return [LocalStore.keyPrefix, key].join(":");
    },

    /**
     * Get whatever data was associated with key
     */
    get: function(key) {
        var data = window.localStorage[LocalStore.cacheKey(key)];

        if (data) {
            return JSON.parse(data);
        }

        return null;
    },

    /**
     * Store data associated with key in localStorage
     */
    set: function(key, data) {
        try {
            window.localStorage[LocalStore.cacheKey(key)] = JSON.stringify(data);
        } catch(e) {
            // If we had trouble storing in localStorage, we may've run over
            // the browser's 5MB limit. This should be rare, but when hit, clear
            // everything out.
            LocalStore.clearAll();
        }
    },

    /**
     * Delete whatever data was associated with key
     */
    del: function(key) {
        delete window.localStorage[this.cacheKey(key)];
    },

    /**
     * Delete all cached objects from localStorage
     */
    clearAll: function() {
        var i = 0;
        while (i < localStorage.length) {
            var key = localStorage.key(i);
            if (key.indexOf(LocalStore.keyPrefix + ":") === 0) {
                delete localStorage[key];
            } else {
                i++;
            }
        }
    }

};
