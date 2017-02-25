# -*- coding: utf-8 -*-
# Copyright 2017 Didier Villevalois
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation

import os.path

from quodlibet import _
from quodlibet.plugins.query import QueryPlugin, QueryPluginError
from quodlibet.query import Query
from quodlibet.query._match import error as QueryError
from quodlibet import get_user_dir


class HistoryQuery(QueryPlugin):
    PLUGIN_ID = "History Query"
    PLUGIN_NAME = _("History Query")
    PLUGIN_DESC = _("Use songs from history in queries."
                  "Syntax is '@(history)'.")
    key = 'history'

    def search(self, data, body):
        from quodlibet import app
        if not hasattr(app.window, 'history'):
            return False
        iter_ = app.window.history.model.find(data)
        return iter_ is not None

    def parse_body(self, body, query_path_=None):
        if body is not None:
            raise QueryPluginError
        return None
