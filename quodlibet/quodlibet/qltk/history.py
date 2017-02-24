# -*- coding: utf-8 -*-
# Copyright 2004-2005 Joe Wreschnig, Michael Urman, Iñigo Serna
#                2016 Nick Boultbee
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation

import os

from gi.repository import Gtk, Gdk

import quodlibet
from quodlibet import ngettext, _
from quodlibet import config
from quodlibet import util
from quodlibet import qltk

from quodlibet.util import connect_obj, connect_destroy, format_time_preferred
from quodlibet.qltk import Icons, gtk_version, add_css
from quodlibet.qltk.ccb import ConfigCheckButton
from quodlibet.qltk.songlist import SongList, DND_QL, DND_URI_LIST
from quodlibet.qltk.songsmenu import SongsMenu
from quodlibet.qltk.songmodel import PlaylistModel
from quodlibet.qltk.playorder import OrderInOrder, OrderShuffle
from quodlibet.qltk.x import ScrolledWindow, SymbolicIconImage, \
    SmallImageButton, MenuItem

HISTORY = os.path.join(quodlibet.get_user_dir(), "history")


class HistoryModel(PlaylistModel):
    """Own class for debugging"""


class History(SongList):

    sortable = False

    class CurrentColumn(Gtk.TreeViewColumn):
        # Match MainSongList column sizes by default.
        header_name = "~current"

        def __init__(self):
            super(History.CurrentColumn, self).__init__()
            self.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            self.set_fixed_width(24)

    def __init__(self, library):
        super(History, self).__init__(library, model_cls=HistoryModel)
        self.set_size_request(-1, 120)

        connect_obj(self, 'popup-menu', self.__popup, library)
        connect_obj(self, 'destroy', self.__write, self.model)
        self.__fill(library)

    def __fill(self, library):
        try:
            with open(HISTORY, "rU") as f:
                filenames = f.readlines()
        except EnvironmentError:
            pass
        else:
            filenames = map(str.strip, filenames)
            if library.librarian:
                library = library.librarian
            songs = filter(None, map(library.get, filenames))
            for song in songs:
                self.model.append([song])

    def __write(self, model):
        filenames = "\n".join([row[0]["~filename"] for row in model])
        with open(HISTORY, "w") as f:
            f.write(filenames)

    def __popup(self, library):
        songs = self.get_selected_songs()
        if not songs:
            return

        menu = SongsMenu(
            library, songs, queue=False, remove=False, delete=False,
            ratings=False)
        menu.preseparate()

        clear = MenuItem(_("_Clear History"), Icons.LIST_REMOVE)
        qltk.add_fake_accel(clear, "Clear")
        clear.connect('activate', self.__clear_history)
        menu.prepend(clear)

        menu.show_all()
        return self.popup_menu(menu, 0, Gtk.get_current_event_time())

    def __clear_history(self, *args):
        self.clear()
