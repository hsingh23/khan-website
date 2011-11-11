from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

from gandalf import dashboard
from gandalf import api

application = webapp.WSGIApplication([
    ("/gandalf/dashboard", dashboard.Dashboard),
    ("/gandalf/api/v1/bridges", api.Bridges),
    ("/gandalf/api/v1/bridges/filters", api.Filters),
    ("/gandalf/api/v1/bridges/update", api.UpdateBridge),
    ("/gandalf/api/v1/bridges/filters/update", api.UpdateFilter),
])

def main():
    run_wsgi_app(application)

if __name__ == "__main__":
    main()
