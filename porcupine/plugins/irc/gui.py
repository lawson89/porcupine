# strongly inspired by xchat :)
# hexchat is a fork of xchat, its developers didn't invent the gui layout
import queue
import time
import tkinter
from tkinter import ttk

import backend


# represents the IRC server, a channel or a PM conversation
class ChannelLikeView:

    # users is None if this is not a channel
    # name is a nick or channel name, or None if this is the first
    # ChannelLikeView ever created, used for server messages
    def __init__(self, ircwidget, name, users=None):
        # if someone changes nick, IrcWidget takes care of updating .name
        self.name = name

        # width and height are minimums
        # IrcWidget packs this and lets this stretch
        self.textwidget = tkinter.Text(ircwidget, width=1, height=1,
                                       state='disabled')

        if users is None:
            self.userlist = None
            self.userlistbox = None
        else:
            # why is there no ttk listbox :(
            # bigpanedw adds this to itself when needed
            self.userlist = list(users)
            self.userlist.sort(key=str.casefold)
            self.userlistbox = tkinter.Listbox(ircwidget, width=15)
            self.userlistbox.insert('end', *self.userlist)

    def destroy_widgets(self):
        self.textwidget.destroy()
        if self.userlistbox is not None:
            self.userlistbox.destroy()

    def add_message(self, sender, message):
        # scroll down all the way if the user hasn't scrolled up manually
        do_the_scroll = (self.textwidget.yview()[1] == 1.0)

        now = time.strftime('%H:%M')
        self.textwidget['state'] = 'normal'
        self.textwidget.insert(
            'end', '[%s] %25s | %s\n' % (now, '<' + sender + '>', message))
        self.textwidget['state'] = 'disabled'

        if do_the_scroll:
            self.textwidget.see('end')

    def on_join(self, nick):
        assert self.name.startswith('#'), "on_join() is for channels only"

        # TODO: a better algorithm?
        #       timsort is good, but maybe sorting every time is not?
        self.userlist.append(nick)
        self.userlist.sort(key=str.casefold)
        index = self.userlist.index(nick)
        self.userlistbox.insert(index, nick)

        self.add_message('*', "%s joined %s." % (nick, self.name))

    def on_part(self, nick, reason):
        assert self.name.startswith('#'), "on_part() is for channels only"

        index = self.userlist.index(nick)
        del self.userlist[index]
        self.userlistbox.delete(index)

        msg = "%s left %s." % (nick, self.name)
        if reason is not None:
            msg = "%s (%s)" % (msg, reason)
        self.add_message('*', msg)

    def on_quit(self, nick, reason):
        if self.name.startswith('#'):   # this is a channel
            index = self.userlist.index(nick)
            del self.userlist[index]
            self.userlistbox.delete(index)
        else:  # this is a PM conversation
            if self.name != nick:
                # this conversation is between the user and someone else
                return

        msg = "%s quit." % nick
        if reason is not None:
            msg = "%s (%s)" % (msg, reason)
        self.add_message('*', msg)

    def _userlist_replace(self, old, new):
        old_index = self.userlist.index(old)
        was_selected = (old_index in self.userlistbox.curselection())
        self.userlistbox.delete(old_index)

        self.userlist[old_index] = new     # replace the old value efficiently
        self.userlist.sort()

        new_index = self.userlist.index(new)
        self.userlistbox.insert(new_index, new)
        if was_selected:
            self.userlistbox.selection_set(new_index)

    # must be ran when this user has successfully changed nick
    def on_self_changed_nick(self, old, new):
        # if this is a channel, update the list of nicks
        if self.userlist is not None:
            self._userlist_replace(old, new)

        # notify about the nick change everywhere, no ifs in front of this
        self.add_message('*', "You are now known as %s." % new)

    # must be ran when another user changes nick, AFTER changing self.name
    def on_user_changed_nick(self, old, new):
        if self.name is None:
            # no need to do anything on the server channel-like
            return

        if self.userlist is None:
            # PM chat, only notify of the nick change if chatting with
            # that nick
            assert not self.name.startswith('#')
            if self.name != new:
                return
        else:
            # a channel, update the user list
            assert self.name.startswith('#')
            if old not in self.userlist:
                return
            self._userlist_replace(old, new)

        self.add_message('*', "%s is now known as %s." % (old, new))


def ask_new_nick(parent, old_nick):
    dialog = tkinter.Toplevel()
    content = ttk.Frame(dialog)
    content.pack(fill='both', expand=True)

    ttk.Label(content, text="Enter a new nickname here:").place(
        relx=0.5, rely=0.1, anchor='center')

    entry = ttk.Entry(content)
    entry.place(relx=0.5, rely=0.3, anchor='center')
    entry.insert(0, old_nick)

    ttk.Label(content, text="The same nick will be used on all channels.",
              justify='center', wraplength=150).place(
        relx=0.5, rely=0.6, anchor='center')

    buttonframe = ttk.Frame(content, borderwidth=5)
    buttonframe.place(relx=1.0, rely=1.0, anchor='se')

    result = old_nick

    def ok(junk_event=None):
        nonlocal result
        result = entry.get()
        dialog.destroy()

    ttk.Button(buttonframe, text="OK", command=ok).pack(side='left')
    ttk.Button(buttonframe, text="Cancel",
               command=dialog.destroy).pack(side='left')
    entry.bind('<Return>', (lambda junk_event: ok()))
    entry.bind('<Escape>', (lambda junk_event: dialog.destroy()))

    dialog.geometry('250x150')
    dialog.resizable(False, False)
    dialog.transient(parent)
    entry.focus()
    dialog.wait_window()

    return result


class IrcWidget(ttk.PanedWindow):

    def __init__(self, master, irc_core, on_quit, **kwargs):
        kwargs.setdefault('orient', 'horizontal')
        super().__init__(master, **kwargs)
        self._core = irc_core
        self._on_quit = on_quit

        self._channel_selector = tkinter.Listbox(self, width=15)
        self._channel_selector.bind('<<ListboxSelect>>', self._on_selection)
        self.add(self._channel_selector, weight=0)   # don't stretch

        self._middle_pane = ttk.Frame(self)
        self.add(self._middle_pane, weight=1)    # always stretch

        entryframe = ttk.Frame(self._middle_pane)
        entryframe.pack(side='bottom', fill='x')
        # TODO: add a tooltip to the button, it's not very obvious
        self._nickbutton = ttk.Button(entryframe, text=irc_core.nick,
                                      command=self._show_change_nick_dialog)
        self._nickbutton.pack(side='left')
        self._entry = ttk.Entry(entryframe)
        self._entry.pack(side='left', fill='both', expand=True)
        self._entry.bind('<Return>', self._on_enter_pressed)

        self._channel_likes = {}   # {channel_like.name: channel_like}
        self._current_channel_like = None  # selected in self._channel_selector

        self.add_channel_like(ChannelLikeView(self, None))

    def focus_the_entry(self):
        self._entry.focus()

    def _show_change_nick_dialog(self):
        new_nick = ask_new_nick(self.winfo_toplevel(), self._core.nick)
        if new_nick != self._core.nick:
            self._core.change_nick(new_nick)

    def _on_enter_pressed(self, event):
        msg = event.widget.get()
        event.widget.delete(0, 'end')

        match = __import__('re').search(r'^(/\w+)(?: (.*))?$', msg)   # lol
        if not match:
            if self._current_channel_like.name is None:   # the server
                self._current_channel_like.add_message(
                    '*', "Cannot send messages here :(")
            else:
                self._core.send_privmsg(self._current_channel_like.name, msg)
            return

        if match.group(1) == '/join':
            self._core.join_channel(match.group(2))
        elif match.group(1) == '/nick':
            self._core.change_nick(match.group(2))
        elif match.group(1) == '/part':
            if match.group(2) is None:
                channel = self._current_channel_like.name
                if channel is None or not channel.startswith('#'):
                    raise ValueError
            else:
                channel = match.group(2)
            self._core.part_channel(channel)
        else:
            raise ValueError

    def _on_selection(self, event):
        (index,) = self._channel_selector.curselection()
        if index == 0:   # the special server channel-like
            new_channel_like = self._channel_likes[None]
        else:
            new_channel_like = self._channel_likes[self._channel_selector.get(
                index)]   # pep8 line length makes for weird-looking code

        if self._current_channel_like is new_channel_like:
            return

        if self._current_channel_like is not None:
            # not running for the first time
            if self._current_channel_like.userlistbox is not None:
                self.remove(self._current_channel_like.userlistbox)
            self._current_channel_like.textwidget.pack_forget()

        new_channel_like.textwidget.pack(
            in_=self._middle_pane, side='top', fill='both', expand=True)
        if new_channel_like.userlistbox is not None:
            self.add(new_channel_like.userlistbox, weight=0)

        self._current_channel_like = new_channel_like

    def _select_index(self, index):
        self._channel_selector.selection_clear(0, 'end')
        self._channel_selector.selection_set(index)
        self._channel_selector.event_generate('<<ListboxSelect>>')

    def add_channel_like(self, channel_like):
        assert channel_like.name not in self._channel_likes
        self._channel_likes[channel_like.name] = channel_like

        if channel_like.name is None:
            # the special server channel-like
            assert len(self._channel_likes) == 1
            self._channel_selector.insert('end', "Server: " + self._core.host)
        else:
            self._channel_selector.insert('end', channel_like.name)
        self._select_index('end')

    # https://xkcd.com/1960/
    def select_something_else(self, than_this_channel_like):
        if than_this_channel_like is not self._current_channel_like:
            return

        # i didn't find a better way to find a listbox index by name
        if self._current_channel_like.name is None:
            index = 0
        else:
            index = self._channel_selector.get(0, 'end').index(
                self._current_channel_like.name)
        if index == len(self._channel_likes) - 1:   # last channel-like
            self._select_index(index - 1)
        else:
            self._select_index(index + 1)

    def remove_channel_like(self, channel_like):
        assert channel_like.name is not None, ("cannot remove the "
                                               "server channel-like")
        self.select_something_else(channel_like)
        index = self._channel_selector.get(0, 'end').index(channel_like.name)
        self._channel_selector.delete(index)
        del self._channel_likes[channel_like.name]
        channel_like.destroy_widgets()

    # this must be called when someone that the user is PM'ing with
    # changes nick
    # channels and the special server channel-like can't be renamed
    def rename_channel_like(self, old_name, new_name):
        assert old_name is not None and new_name is not None, (
            "cannot remove the server channel-like")
        if new_name in self._channel_likes:
            # unlikely to ever happen... lol
            self.remove_channel_like(self._channel_likes[new_name])

        self._channel_likes[new_name] = self._channel_likes.pop(old_name)
        self._channel_likes[new_name].name = new_name

        index = self._channel_selector.get(0, 'end').index(old_name)
        was_selected = (index in self._channel_selector.curselection())
        self._channel_selector.delete(index)
        self._channel_selector.insert(index, new_name)
        if was_selected:
            self._select_index(index)

    def handle_events(self):
        while True:
            try:
                event, *event_args = self._core.event_queue.get(block=False)
            except queue.Empty:
                break

            if event == backend.IrcEvent.self_joined:
                channel, nicklist = event_args
                self.add_channel_like(ChannelLikeView(self, channel, nicklist))

            elif event == backend.IrcEvent.self_changed_nick:
                old, new = event_args
                self._nickbutton['text'] = new
                for channel_like in self._channel_likes.values():
                    channel_like.on_self_changed_nick(old, new)

            elif event == backend.IrcEvent.self_parted:
                [channel] = event_args
                self.remove_channel_like(self._channel_likes[channel])

            elif event == backend.IrcEvent.self_quit:
                self._on_quit()
                return      # don't run self.handle_events again

            elif event == backend.IrcEvent.user_joined:
                nick, channel = event_args
                self._channel_likes[channel].on_join(nick)

            elif event == backend.IrcEvent.user_changed_nick:
                old, new = event_args
                if old in self._channel_likes:   # a PM conversation
                    self.rename_channel_like(old, new)

                for channel_like in self._channel_likes.values():
                    channel_like.on_user_changed_nick(old, new)

            elif event == backend.IrcEvent.user_parted:
                nick, channel, reason = event_args
                self._channel_likes[channel].on_part(nick, reason)

            elif event == backend.IrcEvent.user_quit:
                nick, reason = event_args
                assert not nick.startswith('#')

                for channel_like in self._channel_likes.values():
                    # skip the server channel-like
                    if channel_like.name is None:
                        continue

                    # show a quit message if the user was on this channel
                    # or if this is a PM conversation with that user
                    if (nick == channel_like.name or
                            (channel_like.userlist is not None and
                             nick in channel_like.userlist)):
                        channel_like.on_quit(nick, reason)

            elif event == backend.IrcEvent.sent_privmsg:
                recipient, msg = event_args
                if recipient not in self._channel_likes:
                    # start of a new PM conversation with a nick
                    assert not recipient.startswith('#')
                    self.add_channel_like(ChannelLikeView(self, recipient))

                self._channel_likes[recipient].add_message(
                    self._core.nick, msg)

            elif event == backend.IrcEvent.received_privmsg:
                # sender and recipient are channels or nicks
                sender, recipient, msg = event_args

                if recipient == self._core.nick:     # PM
                    channel_like_name = sender   # whoever sent this
                    if sender not in self._channel_likes:
                        # create a new channel-like for the conversation
                        self.add_channel_like(ChannelLikeView(self, sender))
                else:  # the message has been sent to an entire channel
                    assert recipient.startswith('#')
                    channel_like_name = recipient

                self._channel_likes[channel_like_name].add_message(
                    sender, msg)

            elif event in {backend.IrcEvent.server_message,
                           backend.IrcEvent.unknown_message}:
                server, command, args = event_args
                ircwidget._channel_likes[None].add_message(
                    server, ' '.join(args))

            else:
                raise ValueError("unknown event type " + repr(event))

        self.after(100, self.handle_events)

    def part_all_channels_and_quit(self):
        for name in self._channel_likes.keys():
            if name is not None and name.startswith('#'):
                # TODO: add a reason here?
                self._core.part_channel(name)
        self._core.quit()


if __name__ == '__main__':
    core = backend.IrcCore('chat.freenode.net', 6667, 'testieeeee')
    core.connect()

    root = tkinter.Tk()
    ircwidget = IrcWidget(root, core, root.destroy)
    ircwidget.pack(fill='both', expand=True)

    ircwidget.handle_events()
    ircwidget.focus_the_entry()
    root.protocol('WM_DELETE_WINDOW', ircwidget.part_all_channels_and_quit)

    root.mainloop()