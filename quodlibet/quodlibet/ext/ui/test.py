# -*- coding: utf-8 -*-
# Copyright 2017 Didier Villevalois
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation

from gi.repository import Gdk, Gtk

from quodlibet import _
from quodlibet.plugins.gui import UIPlugin
from quodlibet.qltk import Icons
from quodlibet.util import connect_destroy


class MyTestWidget(Gtk.Box):
    def __init__(self, string, player):
        super(Gtk.Box, self).__init__()

        self._str = string
        self.__label = Gtk.Label(self._str + ": --")
        self.pack_start(self.__label, True, True, 0)

        connect_destroy(player, "seek", self._on_player_seek)

    def _on_player_seek(self, player, song, ms):
        self.__label.set_text(self._str + ": %d ms" % ms)


class TestPlugin(UIPlugin):
    PLUGIN_ID = "TestPlugin"
    PLUGIN_NAME = _("Test Plugin")
    PLUGIN_DESC = _("Test Plugin tests UI placeholders.")
    PLUGIN_ICON = Icons.EDIT
    PLUGIN_VERSION = "0.1"

    def ui_contributions(self):
        return {
            "test-placeholder": self.build_widget
        }

    def build_widget(self, placeholder, player):
        return MyTestWidget("test1", player)


class TestPlugin2(UIPlugin):
    PLUGIN_ID = "TestPlugin2"
    PLUGIN_NAME = _("Test Plugin 2")
    PLUGIN_DESC = _("Test Plugin tests UI placeholders.")
    PLUGIN_ICON = Icons.EDIT
    PLUGIN_VERSION = "0.1"

    def ui_contributions(self):
        return {
            "test-placeholder": self.build_widget
        }

    def build_widget(self, placeholder, player):
        return MyTestWidget("test2", player)
