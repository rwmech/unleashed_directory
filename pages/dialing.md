# Making the dial links work

Every board on the list shows its address as a `telnet://` link. Whether
clicking it does anything depends on what your computer has registered for
that scheme, and on a normal Windows machine the answer is usually nothing.

Here is why, and the fix, in the order most people should try them.

## The short version

Install [SyncTERM](https://syncterm.bbsdev.net/) and let its installer take the
telnet association. It is the right terminal for calling boards anyway, it
understands `telnet://` links including a non-standard port, and it saves
whatever was registered before so uninstalling puts it back.

That is the whole fix for most people. The rest of this page is for when it is
not.

> [!NOTE]
> You never have to touch any of this. The address in the Dial column is
> ordinary text inside the link: select it, copy it, and paste it into your
> terminal. Nothing below is required to call a board.

## Why clicking does nothing on Windows

Two separate things have to be true: some program must be registered for
`telnet://`, and that program must understand a URL as its argument. Both fail
in their own way.

Windows ships a registration pointing at its own Telnet Client, through
`rundll32.exe url.dll,TelnetProtocolHandler`. But Telnet Client is an optional
Windows feature that is **off by default**, so the registration points at a
program that is not installed. Clicking the link launches nothing and reports
nothing.

## Why Tera Term gets blamed

Tera Term's installer has offered to take the telnet association since version
4.59, so it is very often the thing that grabbed it. It is also, on a machine
checked for this page, not actually the thing the browser runs.

Tera Term 5 does not replace the standard `open` verb. It adds a verb of its
own, named `Open with Tera Term`, and points the `shell` key's default at that.
Meanwhile `shell\open\command` still holds the original
`rundll32.exe url.dll,TelnetProtocolHandler`. A browser asks for `open`
explicitly, gets the stock handler, and runs the `telnet.exe` that is not
there.

So the usual symptom is not Tera Term misbehaving. It is Tera Term appearing to
own the association while the thing that actually runs is a dead end.

Worth knowing even when it does launch: Tera Term only begins telnet option
negotiation when the port is 23. On a board running on 6400 it opens the socket
and says nothing, so the board has to work out what it is talking to the slow
way. It still connects, and it is still not the terminal to choose for this.

### Fixing it without a registry editor

Install SyncTERM. Its installer writes the `open` verb properly.

If Tera Term's own verb is still winning afterwards, set the `shell` key's
default value back to `open`, or delete the `Open with Tera Term` verb. That is
a registry edit, so read the next section first.

## Setting the handler by hand, on Windows

> Editing the registry can break unrelated associations, and a mistake is not
> always obvious straight away. Export the key first. Use the `HKEY_CURRENT_USER`
> path below rather than `HKEY_CLASSES_ROOT`: it needs no administrator, applies
> only to you, and takes priority over the machine-wide setting anyway.

Back it up first, in a normal command prompt:

```
reg export HKCU\Software\Classes\telnet telnet-backup.reg
```

Then save this as `telnet.reg`, edit the path to your terminal, and double
click it:

```
Windows Registry Editor Version 5.00

[HKEY_CURRENT_USER\Software\Classes\telnet]
@="URL:Telnet Protocol"
"URL Protocol"=""

[HKEY_CURRENT_USER\Software\Classes\telnet\shell]
@="open"

[HKEY_CURRENT_USER\Software\Classes\telnet\shell\open\command]
@="\"C:\\Program Files\\SyncTERM\\syncterm.exe\" \"%1\""
```

The empty `URL Protocol` value is not decoration. Microsoft's documentation is
explicit that without it the handler will not launch at all.

Windows Settings has an "Apps > Default apps > Choose defaults by link type"
list, but a program only appears there if it declared itself under
`RegisteredApplications` and `Capabilities\UrlAssociations`. Terminal programs
generally do not, so telnet usually will not be in that list. The registry is
the reliable route.

[PuTTY](https://www.chiark.greenend.org.uk/~sgtatham/putty/) also works as a
handler and documents itself as suitable for exactly this, so substitute its
path if you prefer it. Set the character set to CP437 or the art will be wrong.

## macOS

Apple removed the `telnet` command in High Sierra and nothing Apple ships
claims the scheme now. Note that Apple never published a release note saying
so; the evidence is simply that the binary is gone.

An application claims a scheme in its `Info.plist`. To choose between
claimants, the supported tool is `duti`:

```
brew install duti
osascript -e 'id of app "SyncTERM"'
duti -s <the bundle id that printed> telnet
```

The scheme is given bare, with no `://`. Whether SyncTERM's macOS build claims
the scheme by itself is not documented either way, so assume it does not and
set it with `duti`.

If the terminal you want has no bundle identifier at all, the route is an
Automator "Run Shell Script" application with `CFBundleURLTypes` added to its
`Info.plist` by hand, then point `duti` at that. Automator will not add the URL
type for you.

## Linux

A desktop file advertises the scheme as a MIME type. Save this as
`~/.local/share/applications/syncterm-telnet.desktop`:

```
[Desktop Entry]
Type=Application
Name=SyncTERM (telnet)
Exec=syncterm %u
Terminal=true
NoDisplay=true
MimeType=x-scheme-handler/telnet;
```

Then register it:

```
update-desktop-database ~/.local/share/applications
xdg-mime default syncterm-telnet.desktop x-scheme-handler/telnet
xdg-mime query default x-scheme-handler/telnet
```

`xdg-mime default` wants the desktop file's name, not a path to it. `%u` means
one URL and is expanded to a single argument.

## When your terminal cannot read a URL

Every platform hands the handler the whole URL, normally with a trailing
slash: `telnet://host:6400/`. SyncTERM, Tera Term and PuTTY all accept that.
Windows `telnet.exe` does not, because it wants a host and a port as two
separate arguments.

For a program like that, put a small wrapper in between. On Linux, as
`~/bin/telnet-handler.sh`, with `Exec=/home/you/bin/telnet-handler.sh %u`:

```sh
#!/bin/sh
# Split telnet://[user@]host[:port][/] into a host and a port.
u=${1#telnet://}
u=${u#*@}
u=${u%/}
case "$u" in
  *:*) host=${u%%:*}; port=${u##*:} ;;
  *)   host=$u;       port=23 ;;
esac
exec telnet "$host" "$port"
```

On Windows, as `C:\bin\telnet-handler.ps1`:

```powershell
param([string]$Url)
if ($Url -match '^telnet://(?:[^@/]*@)?\[?([^\]:/]+)\]?(?::(\d+))?/?$') {
    $h = $Matches[1]
    $p = if ($Matches[2]) { $Matches[2] } else { '23' }
    Start-Process 'C:\Program Files\PuTTY\putty.exe' -ArgumentList @('-telnet', $h, '-P', $p)
}
```

Registered as:

```
"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "C:\bin\telnet-handler.ps1" "%1"
```

Both scripts match a narrow shape and do nothing at all if the URL does not fit
it. That is deliberate. The string comes from whatever web page was clicked, so
a handler should treat it as hostile: Microsoft's own guidance is that quotes
and backslashes in a URI can split it across several arguments.

## Sources

- [Registering an application to a URI scheme](https://learn.microsoft.com/en-us/previous-versions/windows/internet-explorer/ie-developer/platform-apis/aa767914(v=vs.85))
- [Default programs, UrlAssociations and RegisteredApplications](https://learn.microsoft.com/en-us/windows/win32/shell/default-programs)
- [Install Telnet Client](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-server-2008-r2-and-2008/cc771275(v=ws.10))
- [Tera Term: associate with the telnet protocol](https://teratermproject.github.io/manual/5/en/usage/tips/telnet_protocol.html)
- [Tera Term command line, including the port 23 negotiation note](https://teratermproject.github.io/manual/5/en/commandline/teraterm.html)
- [SyncTERM](https://syncterm.bbsdev.net/) and its [manual](https://syncterm.bbsdev.net/Manual.html)
- [SyncTERM Windows installer, registry writes](https://github.com/bbs-io/syncterm-windows/blob/master/SyncTERM-Setup.template.iss)
- [PuTTY manual, telnet:// URLs](https://the.earth.li/~sgtatham/putty/latest/htmldoc/Chapter3.html)
- [RFC 4248, the telnet URI scheme](https://www.rfc-editor.org/rfc/rfc4248.html)
- [CFBundleURLTypes](https://developer.apple.com/documentation/bundleresources/information-property-list/cfbundleurltypes)
- [duti](https://github.com/moretension/duti/blob/master/README.md)
- [Desktop entry specification, Exec field codes](https://specifications.freedesktop.org/desktop-entry-spec/latest/exec-variables.html)
- [xdg-mime](https://portland.freedesktop.org/doc/xdg-mime.html)
