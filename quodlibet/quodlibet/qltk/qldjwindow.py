# -*- coding: utf-8 -*-
# Copyright 2004-2005 Joe Wreschnig, Michael Urman, Iñigo Serna
#           2012 Christoph Reiter
#           2012-2016 Nick Boultbee
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation

import os

from gi.repository import Gtk, Gdk, GLib, Gio, GObject
from senf import uri2fsn, fsnative

import quodlibet

from quodlibet import browsers
from quodlibet import config
from quodlibet import const
from quodlibet import formats
from quodlibet import qltk
from quodlibet import util
from quodlibet import app
from quodlibet import _
from quodlibet.compat import listfilter

from quodlibet.qltk.appwindow import AppWindow
from quodlibet.update import UpdateDialog
from quodlibet.formats.remote import RemoteFile
from quodlibet.qltk.browser import LibraryBrowser, FilterMenu
from quodlibet.qltk.chooser import choose_folders, choose_files, \
    create_chooser_filter
from quodlibet.qltk.controls import PlayPauseButton, Volume
from quodlibet.qltk.cover import CoverImage
from quodlibet.qltk.getstring import GetStringDialog
from quodlibet.qltk.bookmarks import EditBookmarks
from quodlibet.qltk.shortcuts import show_shortcuts
from quodlibet.qltk.info import SongInfo
from quodlibet.qltk.information import Information
from quodlibet.qltk.history import History
from quodlibet.qltk.msg import ErrorMessage
from quodlibet.qltk.pluginwin import PluginWindow
from quodlibet.qltk.properties import SongProperties
from quodlibet.qltk.prefs import PreferencesWindow
from quodlibet.qltk.queue import PlayQueue
from quodlibet.qltk.quodlibetwindow import ConfirmLibDirSetup, PlaybackErrorDialog
from quodlibet.qltk.msg import WarningMessage
from quodlibet.qltk.songlist import SongList, get_columns, set_columns
from quodlibet.qltk.x import RHPaned, RVPaned, Align, ScrolledWindow, Action
from quodlibet.qltk.x import ToggleAction, RadioAction
from quodlibet.qltk.x import SeparatorMenuItem, MenuItem, CellRendererPixbuf
from quodlibet.qltk.x import SymbolicIconImage, RadioMenuItem
from quodlibet.qltk.x import HighlightToggleButton
from quodlibet.qltk.seekbutton import SeekButton
from quodlibet.qltk import Icons
from quodlibet.qltk.about import AboutDialog
from quodlibet.util import copool, connect_destroy, connect_after_destroy
from quodlibet.util.library import get_scan_dirs, set_scan_dirs
from quodlibet.util import connect_obj, print_d
from quodlibet.util.path import glib2fsn, get_home_dir
from quodlibet.util.library import background_filter, scan_library
from quodlibet.qltk.window import PersistentWindowMixin, Window, on_first_map
from quodlibet.qltk.songlistcolumns import SongListColumn


class DockMenu(Gtk.Menu):
    """Menu used for the OSX dock and the tray icon"""

    def __init__(self, app):
        super(DockMenu, self).__init__()

        player = app.player

        play_item = MenuItem(_("_Play"), Icons.MEDIA_PLAYBACK_START)
        play_item.connect("activate", self._on_play, player)
        pause_item = MenuItem(_("P_ause"), Icons.MEDIA_PLAYBACK_PAUSE)
        pause_item.connect("activate", self._on_pause, player)
        self.append(play_item)
        self.append(pause_item)

        previous = MenuItem(_("Pre_vious"), Icons.MEDIA_SKIP_BACKWARD)
        previous.connect('activate', lambda *args: player.previous())
        self.append(previous)

        next_ = MenuItem(_("_Next"), Icons.MEDIA_SKIP_FORWARD)
        next_.connect('activate', lambda *args: player.next())
        self.append(next_)

        browse = qltk.MenuItem(_("_Browse Library"), Icons.EDIT_FIND)
        browse_sub = Gtk.Menu()
        for Kind in browsers.browsers:
            i = Gtk.MenuItem(label=Kind.accelerated_name, use_underline=True)
            connect_obj(i,
                        'activate', LibraryBrowser.open, Kind, app.library, app.player)
            browse_sub.append(i)

        browse.set_submenu(browse_sub)
        self.append(SeparatorMenuItem())
        self.append(browse)

        self.show_all()
        self.hide()

    def _on_play(self, item, player):
        player.paused = False

    def _on_pause(self, item, player):
        player.paused = True


class CurrentColumn(SongListColumn):
    """Displays the current song indicator, either a play or pause icon."""

    def __init__(self):
        super(CurrentColumn, self).__init__("~current")
        self._render = CellRendererPixbuf()
        self.pack_start(self._render, True)
        self._render.set_property('xalign', 0.5)

        self.set_fixed_width(24)
        self.set_expand(False)
        self.set_cell_data_func(self._render, self._cdf)

    def _format_title(self, tag):
        return u""

    def _cdf(self, column, cell, model, iter_, user_data):
        PLAY = "media-playback-start"
        PAUSE = "media-playback-pause"
        STOP = "media-playback-stop"
        ERROR = "dialog-error"

        row = model[iter_]

        if row.path == model.current_path:
            player = app.player
            if player.error:
                name = ERROR
            elif model.sourced:
                name = [PLAY, PAUSE][player.paused]
            else:
                name = STOP
        else:
            name = None

        if not self._needs_update(name):
            return

        if name is not None:
            gicon = Gio.ThemedIcon.new_from_names(
                [name + "-symbolic", name])
        else:
            gicon = None

        cell.set_property('gicon', gicon)


class MasterPlayControls(Gtk.VBox):

    def __init__(self, player, playlist, library, stop_after_action, ui):
        super(MasterPlayControls, self).__init__(spacing=3)

        row = Gtk.Table(n_rows=1, n_columns=3, homogeneous=True)
        row.set_row_spacings(3)
        row.set_col_spacings(3)

        start = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        start.add(SymbolicIconImage("media-playback-start",
                                    Gtk.IconSize.LARGE_TOOLBAR))
        row.attach(start, 0, 1, 0, 1)

        stop_after = HighlightToggleButton(
            relief=Gtk.ReliefStyle.NONE,
            image=SymbolicIconImage("media-playback-stop",
                                    Gtk.IconSize.LARGE_TOOLBAR))
        stop_after.set_action_name("/Menu/Control/StopAfter")
        row.attach(stop_after, 1, 2, 0, 1)

        self.volume = Volume(player)
        self.volume.set_relief(Gtk.ReliefStyle.NONE)
        row.attach(self.volume, 2, 3, 0, 1)

        # XXX: Adwaita defines a different padding for GtkVolumeButton
        # We force it to 0 here, which works because the other (normal) buttons
        # in the grid set the width/height
        qltk.add_css(self.volume, """
            .button {
                padding: 0px;
            }
        """)

        self.pack_start(row, False, True, 0)

        connect_destroy(
            player, 'song-started', self.__song_started, start, stop_after)
        connect_destroy(
            player, 'paused', self.__update_paused, playlist, start, stop_after, False)
        connect_destroy(
            player, 'unpaused', self.__update_paused, playlist, start, stop_after, True)

        connect_obj(start, 'clicked', self.__start, player, playlist)
        # self.__sigs = []
        for sig in ['row-deleted', 'row-inserted', 'rows-reordered']:
            s = playlist.connect(sig, lambda *args: self.__queue_changed(playlist, player, start))
            # self.__sigs.append(s)
        can_start = player.paused and len(playlist.get()) > 0
        start.set_sensitive(can_start)

        connect_obj(stop_after, 'clicked', self.__stop_after, stop_after, stop_after_action)
        stop_after_menu_item = ui.get_widget("/Menu/Control/StopAfter")
        connect_obj(
            stop_after_menu_item, 'activate', self.__update_stop_after, stop_after, stop_after_action)

        stop_after.set_active(stop_after_action.get_active())

    def __start(self, player, playlist):
        if player.paused and len(playlist.get()) > 0:
            player.paused = False
            if not bool(player.song):
                player.next()

    def __queue_changed(self, playlist, player, start):
        can_start = player.paused and len(playlist.get()) > 0
        start.set_sensitive(can_start)

    def __stop_after(self, stop_after, stop_after_action):
        stop_after_action.set_active(stop_after.get_active())

    def __update_stop_after(self, stop_after, stop_after_action):
        stop_after.set_active(stop_after_action.get_active())

    def __update_paused(self, player, playlist, start, stop_after, state):
        can_start = player.paused and len(playlist.get()) > 0
        start.set_sensitive(can_start)

    def __song_started(self, player, song, start, stop_after):
        stop_after.set_sensitive(bool(song))


class PreviewPlayControls(Gtk.VBox):

    def __init__(self, player, playlist, library):
        super(PreviewPlayControls, self).__init__(spacing=3)

        row = Gtk.Table(n_rows=1, n_columns=4, homogeneous=True)
        row.set_row_spacings(3)
        row.set_col_spacings(3)

        prev = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        prev.add(SymbolicIconImage("media-skip-backward",
                                   Gtk.IconSize.LARGE_TOOLBAR))
        row.attach(prev, 0, 1, 0, 1)

        play = PlayPauseButton()
        row.attach(play, 1, 2, 0, 1)

        next_ = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        next_.add(SymbolicIconImage("media-skip-forward",
                                    Gtk.IconSize.LARGE_TOOLBAR))
        row.attach(next_, 2, 3, 0, 1)

        self.volume = Volume(player)
        self.volume.set_relief(Gtk.ReliefStyle.NONE)
        row.attach(self.volume, 3, 4, 0, 1)

        # XXX: Adwaita defines a different padding for GtkVolumeButton
        # We force it to 0 here, which works because the other (normal) buttons
        # in the grid set the width/height
        qltk.add_css(self.volume, """
            .button {
                padding: 0px;
            }
        """)

        self.pack_start(row, False, True, 0)

        connect_obj(prev, 'clicked', self.__previous, player)
        self._toggle_id = play.connect('toggled', self.__playpause, player)
        play.add_events(Gdk.EventMask.SCROLL_MASK)
        connect_obj(play, 'scroll-event', self.__scroll, player)
        connect_obj(next_, 'clicked', self.__next, player)
        connect_destroy(
            player, 'song-started', self.__song_started, next_, play)
        connect_destroy(
            player, 'paused', self.__on_set_paused_unpaused, play, False)
        connect_destroy(
            player, 'unpaused', self.__on_set_paused_unpaused, play, True)

    def __on_set_paused_unpaused(self, player, button, state):
        # block to prevent a signal cycle in case the paused signal and state
        # get out of sync (shouldn't happen.. but)
        button.handler_block(self._toggle_id)
        button.set_active(state)
        button.handler_unblock(self._toggle_id)

    def __scroll(self, player, event):
        if event.direction in [Gdk.ScrollDirection.UP,
                               Gdk.ScrollDirection.LEFT]:
            player.previous()
        elif event.direction in [Gdk.ScrollDirection.DOWN,
                                 Gdk.ScrollDirection.RIGHT]:
            player.next()

    def __song_started(self, player, song, next, play):
        play.set_active(not player.paused)

    def __playpause(self, button, player):
        if button.get_active() and player.song is None:
            player.reset()
            button.set_active(not player.paused)
        else:
            player.paused = not button.get_active()

    def __previous(self, player):
        player.previous()

    def __next(self, player):
        player.next()


class PlayerBar(Gtk.Toolbar):
    def __init__(self, parent, player, playlist, library, stop_after_action=None, ui=None, preview=True):
        super(PlayerBar, self).__init__()
        self.preview = preview

        all = Gtk.ToolItem()
        self.insert(all, 2)
        all.set_expand(True)

        box = Gtk.Box(spacing=6)
        all.add(box)
        qltk.add_css(self, "GtkToolbar {padding: 3px;}")

        self._left_side = Gtk.VBox()
        box.pack_start(self._left_side, True, True, 0)

        controls_and_text = Gtk.HBox()
        self._left_side.pack_start(controls_and_text, True, True, 0)

        if preview:
            # play controls
            t = PreviewPlayControls(player, playlist, library.librarian)
            self.volume = t.volume

            # only restore the volume in case it is managed locally, otherwise
            # this could affect the system volume
            if not player.has_external_volume:
                player.volume = config.getfloat("memory", "volume")

            connect_destroy(player, "notify::volume", self._on_volume_changed)
            controls_and_text.pack_start(t, False, True, 0)
        else:
            # TODO Add a global control lock button, and
            # Start session, stop after next and fade to next
            t = MasterPlayControls(player, playlist, library.librarian, stop_after_action, ui)
            controls_and_text.pack_start(t, False, True, 0)

        # song text
        info_pattern_path = os.path.join(quodlibet.get_user_dir(), "songinfo")
        text = SongInfo(library.librarian, player, info_pattern_path)
        controls_and_text.pack_start(Align(text, border=3), True, True, 0)

        # cover image
        self.image = CoverImage(resize=True)
        connect_destroy(player, 'song-started', self.__new_song)

        # FIXME: makes testing easier
        if app.cover_manager:
            connect_destroy(
                app.cover_manager, 'cover-changed',
                self.__song_art_changed, library)

        box.pack_start(Align(self.image, border=2), False, True, 0)

        # On older Gtk+ (3.4, at least)
        # setting a margin on CoverImage leads to errors and result in the
        # QL window not beeing visible for some reason.
        assert self.image.props.margin == 0

        for child in self.get_children():
            child.show_all()

        context = self.get_style_context()
        context.add_class("primary-toolbar")

    def set_seekbar_widget(self, widget):
        children = self._left_side.get_children()
        if len(children) > 1:
            self._left_side.remove(children[-1])

        if widget:
            self._left_side.pack_start(widget, False, True, 0)
            widget.set_sensitive(self.preview)

    def _on_volume_changed(self, player, *args):
        config.set("memory", "volume", str(player.volume))

    def __new_song(self, player, song):
        self.image.set_song(song)

    def __song_art_changed(self, player, songs, library):
        self.image.refresh()


class ConfirmQuit(WarningMessage):

    RESPONSE_QUIT = 1

    def __init__(self, parent):
        title = _("Quit ?")
        description = _("Quit while in session ?")

        super(ConfirmQuit, self).__init__(
            parent, title, description, buttons=Gtk.ButtonsType.NONE)

        self.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
        self.add_icon_button(_("_Quit"), Icons.WINDOW_CLOSE,
                             self.RESPONSE_QUIT)
        self.set_default_response(Gtk.ResponseType.CANCEL)


class AppMenu(object):
    """Implements a app menu proxy mirroring some main menu items
    to a new menu and exporting it on the session bus.

    Activation gets proxied back to the main menu actions.
    """

    def __init__(self, window, action_group):
        window.realize()

        self._bus = None
        self._ag_id = None
        self._am_id = None
        window.connect("destroy", self._unexport)

        if window.get_realized():
            self._export(window, action_group)
        else:
            self._id = window.connect("realize", self._realized, action_group)

    def _realized(self, window, ag):
        window.disconnect(self._id)
        self._export(window, ag)

    def _export(self, window, gtk_group):
        actions = [
            ["Preferences", "Plugins"],
            ["RefreshLibrary"],
            ["OnlineHelp", "About", "Quit"],
        ]

        # build the new menu
        menu = Gio.Menu()
        action_names = []
        for group in actions:
            section = Gio.Menu()
            for name in group:
                action = gtk_group.get_action(name)
                assert action
                label = action.get_label()
                section.append(label, "app." + name)
                action_names.append(name)
            menu.append_section(None, section)
        menu.freeze()

        # proxy activate to the old group
        def callback(action, data):
            name = action.get_name()
            gtk_action = gtk_group.get_action(name)
            gtk_action.activate()

        action_group = Gio.SimpleActionGroup()
        for name in action_names:
            action = Gio.SimpleAction.new(name, None)
            action_group.insert(action)
            action.connect("activate", callback)

        # export on the bus
        ag_object_path = "/net/sacredchao/QuodLibet"
        am_object_path = "/net/sacredchao/QuodLibet/menus/appmenu"
        app_id = "net.sacredchao.QuodLibet"

        win = window.get_window()
        if not hasattr(win, "set_utf8_property"):
            # not a GdkX11.X11Window
            print_d("Registering appmenu failed: X11 only")
            return

        # FIXME: this doesn't fail on Windows but takes for ages.
        # Maybe remove some deps to make it fail fast?
        # We don't need dbus anyway there.
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._ag_id = bus.export_action_group(ag_object_path, action_group)
            self._am_id = bus.export_menu_model(am_object_path, menu)
        except GLib.GError as e:
            print_d("Registering appmenu failed: %r" % e)
            return

        self._bus = bus

        win.set_utf8_property("_GTK_UNIQUE_BUS_NAME", bus.get_unique_name())
        win.set_utf8_property("_GTK_APPLICATION_ID", app_id)
        win.set_utf8_property("_GTK_APPLICATION_OBJECT_PATH", ag_object_path)
        win.set_utf8_property("_GTK_APP_MENU_OBJECT_PATH", am_object_path)

    def _unexport(self, window):
        if self._bus:
            self._bus.unexport_action_group(self._ag_id)
            self._bus.unexport_menu_model(self._am_id)
            self._bus = None


MENU = """
<ui>
  <menubar name='Menu'>

    <menu action='File'>
      <menuitem action='AddFolders' always-show-image='true'/>
      <menuitem action='AddFiles' always-show-image='true'/>
      <menuitem action='AddLocation' always-show-image='true'/>
      <separator/>
      <menuitem action='Preferences' always-show-image='true'/>
      <menuitem action='Plugins' always-show-image='true'/>
      <separator/>
      <menuitem action='RefreshLibrary' always-show-image='true'/>
      <separator/>
      <menuitem action='Quit' always-show-image='true'/>
    </menu>

    <menu action='Song'>
      <menuitem action='EditBookmarks' always-show-image='true'/>
      <menuitem action='EditTags' always-show-image='true'/>
      <separator/>
      <menuitem action='Information' always-show-image='true'/>
      <separator/>
      <menuitem action='JumpMaster' always-show-image='true'/>
      <menuitem action='JumpPreview' always-show-image='true'/>
    </menu>

    <menu action='Control'>
      <menuitem action='Start' always-show-image='true'/>
      <menuitem action='StopAfter' always-show-image='true'/>
      <separator/>
      <menuitem action='Previous' always-show-image='true'/>
      <menuitem action='PlayPause' always-show-image='true'/>
      <menuitem action='Next' always-show-image='true'/>
    </menu>

    <menu action='Browse'>
      %(filters_menu)s
      <separator/>
      <menu action='BrowseLibrary' always-show-image='true'>
        %(browsers)s
      </menu>
      <separator />

      %(views)s
    </menu>

    <menu action='Help'>
      <menuitem action='OnlineHelp' always-show-image='true'/>
      <menuitem action='Shortcuts' always-show-image='true'/>
      <menuitem action='SearchHelp' always-show-image='true'/>
      <separator/>
      <menuitem action='CheckUpdates' always-show-image='true'/>
      <menuitem action='About' always-show-image='true'/>
    </menu>

  </menubar>
</ui>
"""


def secondary_browser_menu_items():
    items = (_browser_items('Browser') + ["<separator />"] +
             _browser_items('Browser', True))
    return "\n".join(items)


def browser_menu_items():
    items = (_browser_items('View') + ["<separator />"] +
             _browser_items('View', True))
    return "\n".join(items)


def _browser_items(prefix, external=False):
    return ["<menuitem action='%s%s'/>" % (prefix, kind.__name__)
            for kind in browsers.browsers if kind.uses_main_library ^ external]


DND_URI_LIST, = range(1)


class QuodLibetDJWindow(Window, PersistentWindowMixin, AppWindow):
    def __init__(self, library, player, preview_player, restore_cb=None):
        super(QuodLibetDJWindow, self).__init__(dialog=False)
        self.last_dir = get_home_dir()

        self.__destroyed = False
        self.__update_title(player)
        self.set_default_size(600, 480)

        main_box = Gtk.VBox()
        self.add(main_box)

        self.__player = player
        # create main menubar, load/restore accelerator groups
        self.__library = library
        ui = self.__create_menu(player, library)
        accel_group = ui.get_accel_group()
        self.add_accel_group(accel_group)

        def scroll_and_jump(*args):
            self.__jump_to_current(True, True)

        keyval, mod = Gtk.accelerator_parse("<Primary><shift>J")
        accel_group.connect(keyval, mod, 0, scroll_and_jump)

        # dbus app menu
        # Unity puts the app menu next to our menu bar. Since it only contains
        # menu items also available in the menu bar itself, don't add it.
        if not util.is_unity():
            AppMenu(self, ui.get_action_groups()[0])

        # custom accel map
        accel_fn = os.path.join(quodlibet.get_user_dir(), "accels")
        Gtk.AccelMap.load(accel_fn)
        # save right away so we fill the file with example comments of all
        # accels
        Gtk.AccelMap.save(accel_fn)

        menubar = ui.get_widget("/Menu")

        # Since https://git.gnome.org/browse/gtk+/commit/?id=b44df22895c79
        # toplevel menu items show an empty 16x16 image. While we don't
        # need image items there UIManager creates them by default.
        # Work around by removing the empty GtkImages
        for child in menubar.get_children():
            if isinstance(child, Gtk.ImageMenuItem):
                child.set_image(None)

        main_box.pack_start(menubar, False, True, 0)

        # get the playlist up before other stuff
        self.songlist = SongList(library, player)
        self.songlist.connect("key-press-event", self.__songlist_key_press)
        self.songlist.connect_after(
            'drag-data-received', self.__songlist_drag_data_recv)
        self.song_scroller = ScrolledWindow()
        self.song_scroller.set_policy(
            Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.song_scroller.set_shadow_type(Gtk.ShadowType.IN)
        self.song_scroller.add(self.songlist)

        # The main player's history
        scrolled_history = ScrolledWindow()
        scrolled_history.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_history.set_shadow_type(Gtk.ShadowType.IN)
        self.history = History(library)
        self.history.sortable = False
        self.history.props.expand = True
        scrolled_history.add(self.history)

        # The main player's queue
        scrolled_queue = ScrolledWindow()
        scrolled_queue.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_queue.set_shadow_type(Gtk.ShadowType.IN)
        self.queue = PlayQueue(library, player, False)
        self.queue.props.expand = True
        scrolled_queue.add(self.queue)

        self.playlist = self.queue.model

        main_player_bar = PlayerBar(self, player, self.playlist, library, self.stop_after, ui, False)
        self.main_player_bar = main_player_bar

        self.__browserbox = Align(bottom=3)

        # Left-side history and player-queue with a split pane

        left_side = RVPaned()
        left_side.set_relative(config.getfloat("memory", "dj-vsplit", 0.5))

        def on_vsplit_changed(sp, param):
            config.set("memory", "dj-vsplit", str(sp.get_relative()))

        left_side.connect("notify::position", on_vsplit_changed)

        left_side.pack1(scrolled_history, True, True)
        player_and_queue = Gtk.VBox()
        player_and_queue.pack_start(main_player_bar, False, True, 0)
        player_and_queue.pack_start(scrolled_queue, True, True, 0)
        left_side.pack2(player_and_queue, True, True)

        # Right-side browser and preview player

        right_side = Gtk.VBox()

        self.songpane = Gtk.VBox()
        self.songpane.pack_start(self.song_scroller, True, True, 0)
        self.songpane.show_all()

        right_side.pack_start(self.__browserbox, True, True, 0)

        if preview_player:
            preview_player_bar = PlayerBar(self, preview_player, self.songlist.model, library)
            self.preview_player_bar = preview_player_bar

            right_side.pack_end(preview_player_bar, False, True, 0)

        # Horizontal player and browser split pane

        split_pane = RHPaned()
        split_pane.pack1(left_side, True, True)
        split_pane.pack2(right_side, True, True)

        split_pane.set_relative(
            config.getfloat("memory", "dj-horizontalsplit", 0.5))

        def on_vsplit_changed(sp, param):
            config.set("memory", "dj-horizontalsplit", str(sp.get_relative()))

        split_pane.connect("notify::position", on_vsplit_changed)

        main_box.pack_start(split_pane, True, True, 0)

        # Configure events

        try:
            orders = []
            for e in config.getstringlist('memory', 'sortby', []):
                orders.append((e[1:], int(e[0])))
        except ValueError:
            pass
        else:
            self.songlist.set_sort_orders(orders)

        self.browser = None
        self.ui = ui

        main_box.show_all()

        self._playback_error_dialog = None
        connect_destroy(player, 'song-started', self.__master_song_started)
        connect_destroy(player, 'paused', self.__master_update_paused, True)
        connect_destroy(player, 'unpaused', self.__master_update_paused, False)
        # make sure we redraw all error indicators before opening
        # a dialog (blocking the main loop), so connect after default handlers
        connect_after_destroy(player, 'error', self.__player_error)
        # connect after to let SongTracker update stats
        connect_after_destroy(player, "song-ended", self.__master_song_ended)

        # set at least the playlist. the song should be restored
        # after the browser emits the song list
        player.setup(self.playlist, None, 0)
        self.__restore_cb = restore_cb
        self.__first_browser_set = True

        # self.__sigs = []
        for sig in ['row-deleted', 'row-inserted', 'rows-reordered']:
            s = self.playlist.connect(sig, self.__queue_changed)
            # self.__sigs.append(s)

        self.__queue_changed()

        try:
            self._select_browser(
                self, config.get("memory", "browser"), library, player, True)
        except:
            config.set("memory", "browser", browsers.name(browsers.default))
            config.save()
            raise

        self.songlist.connect('row-activated', self.__prelisten, preview_player)
        self.songlist.connect('popup-menu', self.__songs_popup_menu)
        self.songlist.connect('columns-changed', self.__cols_changed)
        self.songlist.connect('columns-changed', self.__hide_headers)
        self.songlist.info.connect("changed", self.__set_totals)

        if preview_player:
            self.preview_playlist = self.songlist.model
            preview_player.setup(self.songlist.model, None, 0)

            connect_destroy(preview_player, 'song-started', self.__preview_song_started)
            connect_destroy(preview_player, 'paused', self.__preview_update_paused, True)
            connect_destroy(preview_player, 'unpaused', self.__preview_update_paused, False)
            # make sure we redraw all error indicators before opening
            # a dialog (blocking the main loop), so connect after default handlers
            connect_after_destroy(preview_player, 'error', self.__player_error)
            # connect after to let SongTracker update stats
            connect_after_destroy(preview_player, "song-ended", self.__preview_song_ended)

        lib = library.librarian
        connect_destroy(lib, 'changed', self.__master_song_changed, player)
        connect_destroy(lib, 'changed', self.__preview_song_changed, preview_player)

        targets = [("text/uri-list", Gtk.TargetFlags.OTHER_APP, DND_URI_LIST)]
        targets = [Gtk.TargetEntry.new(*t) for t in targets]

        self.drag_dest_set(
            Gtk.DestDefaults.ALL, targets, Gdk.DragAction.COPY)
        self.connect('drag-data-received', self.__drag_data_received)

        on_first_map(self, self.__configure_scan_dirs, library)

        if config.getboolean('library', 'refresh_on_start'):
            self.__rebuild(None, False)

        self.connect("key-press-event", self.__key_pressed, preview_player)

        self.connect("destroy", self.__destroy)

        self.enable_window_tracking("quodlibet")

    def set_seekbar_provider(self, provider):
        """Set the seek bar widget provider.

        Args:
            provider (SeekBarProvider):
                a new provider or None to remove the current one
        """

        self.main_player_bar.set_seekbar_widget(
            provider.create_seekbar_widget(app.player, app.librarian))
        self.preview_player_bar.set_seekbar_widget(
            provider.create_seekbar_widget(app.preview_player, app.librarian))

    def set_as_osx_window(self, osx_app):
        assert osx_app

        self._dock_menu = DockMenu(app)
        osx_app.set_dock_menu(self._dock_menu)

        menu = self.ui.get_widget("/Menu")
        menu.hide()
        osx_app.set_menu_bar(menu)
        # Reparent some items to the "Application" menu
        item = self.ui.get_widget('/Menu/Help/About')
        osx_app.insert_app_menu_item(item, 0)
        osx_app.insert_app_menu_item(Gtk.SeparatorMenuItem(), 1)
        item = self.ui.get_widget('/Menu/File/Preferences')
        osx_app.insert_app_menu_item(item, 2)
        quit_item = self.ui.get_widget('/Menu/File/Quit')
        quit_item.hide()

    def get_is_persistent(self):
        return True

    def open_file(self, filename):
        assert isinstance(filename, fsnative)

        song = self.__library.add_filename(filename, add=False)
        if song is not None:
            if self.__player.go_to(song):
                self.__player.paused = False
            return True
        else:
            return False

    def __player_error(self, player, song, player_error):
        # it's modal, but mmkeys etc. can still trigger new ones
        if self._playback_error_dialog:
            self._playback_error_dialog.destroy()
        dialog = PlaybackErrorDialog(self, player_error)
        self._playback_error_dialog = dialog
        dialog.run()
        self._playback_error_dialog = None

    def __configure_scan_dirs(self, library):
        """Get user to configure scan dirs, if none is set up"""
        if not get_scan_dirs() and not len(library) and \
                quodlibet.is_first_session("quodlibet"):
            print_d("Couldn't find any scan dirs")

            resp = ConfirmLibDirSetup(self).run()
            if resp == ConfirmLibDirSetup.RESPONSE_SETUP:
                prefs = PreferencesWindow(self)
                prefs.set_page("library")
                prefs.show()

    def __keyboard_shortcuts(self, action):
        show_shortcuts(self)

    def __edit_bookmarks(self, librarian, player):
        if player.song:
            window = EditBookmarks(self, librarian, player)
            window.show()

    def __key_pressed(self, widget, event, player):
        if not player.song:
            return

        def seek_relative(seconds):
            current = player.get_position()
            current += seconds * 1000
            current = min(player.song("~#length") * 1000 - 1, current)
            current = max(0, current)
            player.seek(current)

        if qltk.is_accel(event, "<alt>Right"):
            seek_relative(10)
            return True
        elif qltk.is_accel(event, "<alt>Left"):
            seek_relative(-10)
            return True

    def __quit(self, *args):
        # Check that master player is not playing
        if not app.player.paused:
            resp = ConfirmQuit(self).run()
            if resp != ConfirmQuit.RESPONSE_QUIT:
                return

        self.destroy()

    def __destroy(self, *args):
        # self.playlist.destroy()

        # The tray icon plugin tries to unhide QL because it gets disabled
        # on Ql exit. The window should stay hidden after destroy.
        self.show = lambda: None
        self.present = self.show

    def __drag_data_received(self, widget, ctx, x, y, sel, tid, etime):
        assert tid == DND_URI_LIST

        uris = sel.get_uris()

        dirs = []
        error = False
        for uri in uris:
            try:
                filename = uri2fsn(uri)
            except ValueError:
                filename = None

            if filename is not None:
                loc = os.path.normpath(filename)
                if os.path.isdir(loc):
                    dirs.append(loc)
                else:
                    loc = os.path.realpath(loc)
                    if loc not in self.__library:
                        self.__library.add_filename(loc)
            elif app.player.can_play_uri(uri):
                if uri not in self.__library:
                    self.__library.add([RemoteFile(uri)])
            else:
                error = True
                break
        Gtk.drag_finish(ctx, not error, False, etime)
        if error:
            ErrorMessage(
                self, _("Unable to add songs"),
                _("%s uses an unsupported protocol.") % util.bold(uri)).run()
        else:
            if dirs:
                copool.add(
                    self.__library.scan, dirs,
                    cofuncid="library", funcid="library")

    def __songlist_key_press(self, songlist, event):
        return self.browser.key_pressed(event)

    def __songlist_drag_data_recv(self, view, *args):
        if self.browser.can_reorder:
            songs = view.get_songs()
            self.browser.reordered(songs)
        self.songlist.clear_sort()

    def __create_menu(self, player, library):
        def add_view_items(ag):
            act = Action(name="Information", label=_('_Information'),
                         icon_name=Icons.DIALOG_INFORMATION)
            act.connect('activate', self.__current_song_info)
            ag.add_action(act)

            act = Action(name="JumpMaster",
                         label=_('_Jump to Master Playing Song'),
                         icon_name=Icons.GO_JUMP)
            act.connect('activate', self.__jump_to_current_master)
            ag.add_action_with_accel(act, "<Primary><shift>J")

            act = Action(name="JumpPreview",
                         label=_('_Jump to Preview Playing Song'),
                         icon_name=Icons.GO_JUMP)
            act.connect('activate', self.__jump_to_current_preview)
            ag.add_action_with_accel(act, "<Primary>J")

        def add_top_level_items(ag):
            ag.add_action(Action(name="File", label=_("_File")))
            ag.add_action(Action(name="Song", label=_("_Song")))
            ag.add_action(Action(name="View", label=_('_View')))
            ag.add_action(Action(name="Browse", label=_("_Browse")))
            ag.add_action(Action(name="Control", label=_('_Control')))
            ag.add_action(Action(name="Help", label=_('_Help')))

        ag = Gtk.ActionGroup.new('QuodLibetWindowActions')
        add_top_level_items(ag)
        add_view_items(ag)

        act = Action(name="AddFolders", label=_(u'_Add a Folder…'),
                     icon_name=Icons.LIST_ADD)
        act.connect('activate', self.open_chooser)
        ag.add_action_with_accel(act, "<Primary>O")

        act = Action(name="AddFiles", label=_(u'_Add a File…'),
                     icon_name=Icons.LIST_ADD)
        act.connect('activate', self.open_chooser)
        ag.add_action(act)

        act = Action(name="AddLocation", label=_(u'_Add a Location…'),
                     icon_name=Icons.LIST_ADD)
        act.connect('activate', self.open_location)
        ag.add_action(act)

        act = Action(name="BrowseLibrary", label=_('Open _Browser'),
                     icon_name=Icons.EDIT_FIND)
        ag.add_action(act)

        act = Action(name="Preferences", label=_('_Preferences'),
                     icon_name=Icons.PREFERENCES_SYSTEM)
        act.connect('activate', self.__preferences)
        ag.add_action(act)

        act = Action(name="Plugins", label=_('_Plugins'),
                     icon_name=Icons.SYSTEM_RUN)
        act.connect('activate', self.__plugins)
        ag.add_action(act)

        act = Action(name="Quit", label=_('_Quit'),
                     icon_name=Icons.APPLICATION_EXIT)
        act.connect('activate', self.__quit)
        ag.add_action_with_accel(act, "<Primary>Q")

        act = Action(name="EditTags", label=_('Edit _Tags'),
                     icon_name=Icons.DOCUMENT_PROPERTIES)
        act.connect('activate', self.__current_song_prop)
        ag.add_action(act)

        act = Action(name="EditBookmarks", label=_(u"Edit Bookmarks…"))
        connect_obj(act, 'activate', self.__edit_bookmarks,
                    library.librarian, player)
        ag.add_action_with_accel(act, "<Primary>B")

        act = Action(name="Start", label=_("Start Session"),
                     icon_name=Icons.MEDIA_PLAYBACK_START)
        act.connect('activate', self.__start_session)
        ag.add_action(act)

        act = ToggleAction(name="StopAfter", label=_("Stop Session After This Song"))
        ag.add_action(act)

        # access point for the tray icon
        self.stop_after = act

        act = Action(name="Previous", label=_('Pre_vious'),
                     icon_name=Icons.MEDIA_SKIP_BACKWARD)
        act.connect('activate', self.__previous_song)
        ag.add_action_with_accel(act, "<Primary>comma")

        act = Action(name="PlayPause", label=_('_Play'),
                     icon_name=Icons.MEDIA_PLAYBACK_START)
        act.connect('activate', self.__play_pause)
        ag.add_action_with_accel(act, "<Primary>space")

        act = Action(name="Next", label=_('_Next'),
                     icon_name=Icons.MEDIA_SKIP_FORWARD)
        act.connect('activate', self.__next_song)
        ag.add_action_with_accel(act, "<Primary>period")

        act = Action(name="Shortcuts", label=_("_Keyboard Shortcuts"))
        act.connect('activate', self.__keyboard_shortcuts)
        ag.add_action_with_accel(act, "<Primary>question")

        act = Action(name="About", label=_("_About"),
                     icon_name=Icons.HELP_ABOUT)
        act.connect('activate', self.__show_about)
        ag.add_action_with_accel(act, None)

        act = Action(name="OnlineHelp", label=_("Online Help"),
                     icon_name=Icons.HELP_BROWSER)

        def website_handler(*args):
            util.website(const.ONLINE_HELP)

        act.connect('activate', website_handler)
        ag.add_action_with_accel(act, "F1")

        act = Action(name="SearchHelp", label=_("Search Help"))

        def search_help_handler(*args):
            util.website(const.SEARCH_HELP)

        act.connect('activate', search_help_handler)
        ag.add_action_with_accel(act, None)

        act = Action(name="CheckUpdates", label=_("_Check for Updates…"),
                     icon_name=Icons.NETWORK_SERVER)

        def check_updates_handler(*args):
            d = UpdateDialog(self)
            d.run()
            d.destroy()

        act.connect('activate', check_updates_handler)
        ag.add_action_with_accel(act, None)

        act = Action(
            name="RefreshLibrary", label=_("_Scan Library"),
            icon_name=Icons.VIEW_REFRESH)
        act.connect('activate', self.__rebuild, False)
        ag.add_action(act)

        current = config.get("memory", "browser")
        try:
            browsers.get(current)
        except ValueError:
            current = browsers.name(browsers.default)

        first_action = None
        for Kind in browsers.browsers:
            name = browsers.name(Kind)
            index = browsers.index(name)
            action_name = "View" + Kind.__name__
            act = RadioAction(name=action_name, label=Kind.accelerated_name,
                              value=index)
            act.join_group(first_action)
            first_action = first_action or act
            if name == current:
                act.set_active(True)
            ag.add_action_with_accel(act, "<Primary>%d" % ((index + 1) % 10,))
        assert first_action
        self._browser_action = first_action

        def action_callback(view_action, current_action):
            current = browsers.name(
                browsers.get(current_action.get_current_value()))
            self._select_browser(view_action, current, library, player)

        first_action.connect("changed", action_callback)

        for Kind in browsers.browsers:
            action = "Browser" + Kind.__name__
            label = Kind.accelerated_name
            act = Action(name=action, label=label)

            def browser_activate(action, Kind):
                LibraryBrowser.open(Kind, library, player)

            act.connect('activate', browser_activate, Kind)
            ag.add_action_with_accel(act, None)

        ui = Gtk.UIManager()
        ui.insert_action_group(ag, -1)

        menustr = MENU % {
            "views": browser_menu_items(),
            "browsers": secondary_browser_menu_items(),
            "filters_menu": FilterMenu.MENU
        }
        ui.add_ui_from_string(menustr)
        self._filter_menu = FilterMenu(library, player, ui)

        # Cute. So. UIManager lets you attach tooltips, but when they're
        # for menu items, they just get ignored. So here I get to actually
        # attach them.
        ui.get_widget("/Menu/File/RefreshLibrary").set_tooltip_text(
            _("Check for changes in your library"))

        return ui

    def __show_about(self, *args):
        about = AboutDialog(self, app)
        about.run()
        about.destroy()

    def select_browser(self, browser_key, library, player):
        """Given a browser name (see browsers.get()) changes the current
        browser.

        Returns True if the passed browser ID is known and the change
        was initiated.
        """

        try:
            Browser = browsers.get(browser_key)
        except ValueError:
            return False

        action_name = "View%s" % Browser.__name__
        for action in self._browser_action.get_group():
            if action.get_name() == action_name:
                action.set_active(True)
                return True
        return False

    def _select_browser(self, activator, current, library, player,
                        restore=False):

        Browser = browsers.get(current)

        config.set("memory", "browser", current)
        if self.browser:
            if not (self.browser.uses_main_library and
                        Browser.uses_main_library):
                self.songlist.clear()
            container = self.browser.__container
            self.browser.unpack(container, self.songpane)
            if self.browser.accelerators:
                self.remove_accel_group(self.browser.accelerators)
            container.destroy()
            self.browser.destroy()
        self.browser = Browser(library)
        self.browser.connect('songs-selected',
                             self.__browser_cb, library, player)
        self.browser.connect('songs-activated', self.__browser_activate)
        if restore:
            self.browser.restore()
            self.browser.activate()
        self.browser.finalize(restore)
        if self.browser.can_reorder:
            self.songlist.enable_drop()
        elif self.browser.dropped:
            self.songlist.enable_drop(False)
        else:
            self.songlist.disable_drop()
        if self.browser.accelerators:
            self.add_accel_group(self.browser.accelerators)

        container = self.browser.__container = self.browser.pack(self.songpane)

        player.replaygain_profiles[1] = self.browser.replaygain_profiles
        player.reset_replaygain()
        self.__browserbox.add(container)
        container.show()
        self._filter_menu.set_browser(self.browser)
        self.__hide_headers()

    def __master_update_paused(self, player, paused):
        can_start = player.paused and len(self.playlist.get()) > 0
        self.ui.get_widget("/Menu/Control/Start").set_sensitive(can_start)

    def __master_song_ended(self, player, song, stopped):
        if song is not None:
            self.history.add_songs([song])
            self.history.jump_to_song(song, select=False)

        # Check if the song should be removed, based on the
        # active filter of the current browser.
        active_filter = self.browser.active_filter
        if song and active_filter and not active_filter(song):
            iter_ = self.songlist.model.find(song)
            if iter_:
                self.songlist.remove_iters([iter_])

        if self.stop_after.get_active():
            player.paused = True
            self.stop_after.set_active(False)

    def __master_song_changed(self, library, songs, player):
        if player.info in songs:
            self.__update_title(player)

    def __queue_changed(self, *args):
        can_start = app.player.paused and len(self.playlist.get()) > 0
        self.ui.get_widget("/Menu/Control/Start").set_sensitive(can_start)

    def __update_title(self, player):
        song = player.info
        title = "Quod Libet"
        if song:
            title = song.comma("~title~version~~people") + " - " + title
        self.set_title(title)

    def __master_song_started(self, player, song):
        self.__update_title(player)

        for wid in ["Control/StopAfter",
                    "Song/EditTags", "Song/Information",
                    "Song/EditBookmarks", "Song/JumpMaster"]:
            self.ui.get_widget('/Menu/' + wid).set_sensitive(bool(song))

        if song is not None:
            iter = self.queue.model.find(song)
            if iter:
                self.queue.model.remove(iter)

    def __preview_update_paused(self, player, paused):
        menu = self.ui.get_widget("/Menu/Control/PlayPause")
        image = menu.get_image()

        if paused:
            label, icon = _("_Play"), Icons.MEDIA_PLAYBACK_START
        else:
            label, icon = _("P_ause"), Icons.MEDIA_PLAYBACK_PAUSE

        menu.set_label(label)
        image.set_from_icon_name(icon, Gtk.IconSize.MENU)

    def __preview_song_ended(self, player, song, stopped):
        pass

    def __preview_song_changed(self, library, songs, player):
        pass

    def __preview_song_started(self, player, song):
        for wid in ["Control/Next", "Song/JumpPreview"]:
            self.ui.get_widget('/Menu/' + wid).set_sensitive(bool(song))

    def __start_session(self, *args):
        if app.player.paused and len(self.playlist.get()) > 0:
            app.player.paused = False
            if not bool(app.player.song):
                app.player.next()

    def __prelisten(self, widget, indices, col, player):
        self._activated = True
        model = self.preview_playlist
        iter = model.get_iter(indices)
        if player.go_to(iter, explicit=True, source=model):
            player.paused = False

    def __play_pause(self, *args):
        if app.preview_player.song is None:
            app.preview_player.reset()
        else:
            app.preview_player.paused ^= True

    def __jump_to_current_master(self, explicit, force_scroll=False):
        """Select/scroll to the current playing song in the playlist.
        If it can't be found tell the browser to properly fill the playlist
        with an appropriate selection containing the song.

        explicit means that the jump request comes from the user and not
        from an event like song-started.

        force_scroll will ask the browser to refill the playlist in any case.
        """

        song = app.player.song
        self.__jump_to_current(song, explicit, force_scroll)

    def __jump_to_current_preview(self, explicit, force_scroll=False):
        """Select/scroll to the current playing song in the playlist.
        If it can't be found tell the browser to properly fill the playlist
        with an appropriate selection containing the song.

        explicit means that the jump request comes from the user and not
        from an event like song-started.

        force_scroll will ask the browser to refill the playlist in any case.
        """

        song = app.preview_player.song
        self.__jump_to_current(song, explicit, force_scroll)

    def __jump_to_current(self, song, explicit, force_scroll=False):
        """Select/scroll to the current playing song in the playlist.
        If it can't be found tell the browser to properly fill the playlist
        with an appropriate selection containing the song.

        explicit means that the jump request comes from the user and not
        from an event like song-started.

        force_scroll will ask the browser to refill the playlist in any case.
        """

        def idle_jump_to(song, select):
            ok = self.songlist.jump_to_song(song, select=select)
            if ok:
                self.songlist.grab_focus()
            return False

        # We are not playing a song
        if song is None:
            return

        if not force_scroll:
            ok = self.songlist.jump_to_song(song, select=explicit)
        else:
            assert explicit
            ok = False

        if ok:
            self.songlist.grab_focus()
        elif explicit:
            # if we can't find it and the user requested it, try harder
            self.browser.scroll(song)
            # We need to wait until the browser has finished
            # scrolling/filling and the songlist is ready.
            # Not perfect, but works for now.
            GLib.idle_add(
                idle_jump_to, song, explicit, priority=GLib.PRIORITY_LOW)

    def __next_song(self, *args):
        app.preview_player.next()

    def __previous_song(self, *args):
        app.preview_player.previous()

    def __rebuild(self, activator, force):
        scan_library(self.__library, force)

    # Set up the preferences window.
    def __preferences(self, activator):
        window = PreferencesWindow(self)
        window.show()

    def __plugins(self, activator):
        window = PluginWindow(self)
        window.show()

    def open_location(self, action):
        name = GetStringDialog(self, _("Add a Location"),
                               _("Enter the location of an audio file:"),
                               button_label=_("_Add"), button_icon=Icons.LIST_ADD).run()
        if name:
            if not util.uri_is_valid(name):
                ErrorMessage(
                    self, _("Unable to add location"),
                    _("%s is not a valid location.") % (
                        util.bold(util.escape(name)))).run()
            elif not app.player.can_play_uri(name):
                ErrorMessage(
                    self, _("Unable to add location"),
                    _("%s uses an unsupported protocol.") % (
                        util.bold(util.escape(name)))).run()
            else:
                if name not in self.__library:
                    self.__library.add([RemoteFile(name)])

    def open_chooser(self, action):
        if action.get_name() == "AddFolders":
            fns = choose_folders(self, _("Add Music"), _("_Add Folders"))
            if fns:
                # scan them
                copool.add(self.__library.scan, fns, cofuncid="library",
                           funcid="library")
        else:
            patterns = ["*" + path2fsn(k) for k in formats.loaders.keys()]
            choose_filter = create_chooser_filter(_("Music Files"), patterns)
            fns = choose_files(
                self, _("Add Music"), _("_Add Files"), choose_filter)
            if fns:
                for filename in fns:
                    self.__library.add_filename(filename)

    def __songs_popup_menu(self, songlist):
        path, col = songlist.get_cursor()
        header = col.header_name
        menu = self.songlist.Menu(header, self.browser, self.__library)
        if menu is not None:
            return self.songlist.popup_menu(menu, 0,
                                            Gtk.get_current_event_time())

    def __current_song_prop(self, *args):
        song = app.player.song
        if song:
            librarian = self.__library.librarian
            window = SongProperties(librarian, [song], parent=self)
            window.show()

    def __current_song_info(self, *args):
        song = app.player.song
        if song:
            librarian = self.__library.librarian
            window = Information(librarian, [song], self)
            window.show()

    def __browser_activate(self, browser):
        app.player.reset()

    def __browser_cb(self, browser, songs, sorted, library, player):
        if browser.background:
            bg = background_filter()
            if bg:
                songs = listfilter(bg, songs)
        self.songlist.set_songs(songs, sorted)

        # After the first time the browser activates, which should always
        # happen if we start up and restore, restore the playing song.
        # Because the browser has send us songs we can be sure it has
        # registered all its libraries.
        if self.__first_browser_set:
            self.__first_browser_set = False

            song = library.librarian.get(config.get("memory", "song"))
            seek_pos = config.getfloat("memory", "seek", 0)
            config.set("memory", "seek", 0)
            if song is not None:
                player.setup(self.playlist, song, seek_pos)

            if self.__restore_cb:
                self.__restore_cb()
                self.__restore_cb = None

    def __hide_headers(self, activator=None):
        for column in self.songlist.get_columns():
            if self.browser.headers is None:
                column.set_visible(True)
            else:
                for tag in util.tagsplit(column.header_name):
                    if tag in self.browser.headers:
                        column.set_visible(True)
                        break
                else:
                    column.set_visible(False)

    def __cols_changed(self, songlist):
        headers = [col.header_name for col in songlist.get_columns()]
        try:
            headers.remove('~current')
        except ValueError:
            pass
        if len(headers) == len(get_columns()):
            # Not an addition or removal (handled separately)
            set_columns(headers)
            SongList.headers = headers

    def __make_query(self, query):
        if self.browser.can_filter_text():
            self.browser.filter_text(query.encode('utf-8'))
            self.browser.activate()

    def __set_totals(self, info, songs):
        length = sum(song.get("~#length", 0) for song in songs)
        t = self.browser.status_text(count=len(songs),
                                     time=util.format_time_preferred(length))
        # self.statusbar.set_default_text(t)
