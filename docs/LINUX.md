# Linux setup

The tools use the system HIDAPI library and access the keyboard through
`/dev/hidraw*`.

On Debian/Ubuntu:

```bash
sudo apt install libhidapi-hidraw0
sudo install -m 0644 udev/99-wobkey-crush80.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

The current user must belong to `plugdev`. Disconnect and reconnect the
keyboard after installing the rule. The OTA tool selects VID `320f`, PID
`5055`, usage page `ffef` and rejects ambiguous device selection.
