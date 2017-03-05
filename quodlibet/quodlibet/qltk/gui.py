# -*- coding: utf-8 -*-
# Copyright 2017 Didier Villevalois
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation

from gi.repository import GObject, Gdk, Gtk

from quodlibet.compat import iteritems
from quodlibet.plugins import PluginManager, PluginHandler
from quodlibet.plugins.gui import UIPlugin


class UIPluginHandler(PluginHandler):

    def __init__(self):
        self.__contributions = {}

    def contributions(self, placeholder):
        if placeholder not in self.__contributions:
            self.__contributions[placeholder] = UIContributions()
        return self.__contributions[placeholder]

    def plugin_handle(self, plugin):
        return issubclass(plugin.cls, UIPlugin)

    def plugin_enable(self, plugin):
        instance = plugin.get_instance()
        for placeholder, contribution in iteritems(instance.ui_contributions()):
            if placeholder not in self.__contributions:
                self.__contributions[placeholder] = UIContributions()
            self.__contributions[placeholder].enable(contribution)

    def plugin_disable(self, plugin):
        instance = plugin.get_instance()
        for placeholder, contribution in iteritems(instance.ui_contributions()):
            if placeholder in self.__contributions:
                self.__contributions[placeholder].disable(contribution)


class UIContributions(GObject.GObject):

    __gsignals__ = {
        'enabled': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'disabled': (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    def __init__(self):
        super(UIContributions, self).__init__()
        self._items = []

    @property
    def items(self):
        return self._items

    def enable(self, item):
        if item not in self._items:
            self._items.append(item)
            self.emit('enabled', item)

    def disable(self, item):
        if item in self._items:
            self._items.remove(item)
            self.emit('disabled', item)


class UI(object):
    plugins = UIPluginHandler()

    @classmethod
    def init_plugins(cls):
        PluginManager.instance.register_handler(cls.plugins)


class WidgetPlaceholder(Gtk.Box):

    def __init__(self, placeholder, *params, **kwargs):
        super(Gtk.Box, self).__init__(**kwargs)
        self._placeholder = placeholder
        self._params = params
        self._contributed = {}

        self._contributions = UI.plugins.contributions(placeholder)
        for item in self._contributions.items:
            contributed = item(placeholder, *params)
            if contributed:
                self._contributed[item] = contributed
                self.add(contributed)
        self.fix_visibility()

        # TODO store signal connection ids to disconnect later
        self._contributions.connect('enabled', self.__enabled)
        self._contributions.connect('disabled', self.__disabled)

    def __enabled(self, contributions, item):
        contributed = item(self._placeholder, *self._params)
        if contributed:
            self._contributed[item] = contributed
            self.add(contributed)
            self.fix_visibility()

    def __disabled(self, contributions, item):
        self.remove(self._contributed[item])
        self.fix_visibility()

    def fix_visibility(self):
        if len(self.get_children()) == 0:
            self.set_no_show_all(True)
            self.hide()
        else:
            self.set_no_show_all(False)
            self.show_all()
