# GUI authorization for removing cmatrix

If you want a graphical authorization prompt instead of a terminal sudo prompt, use `pkexec` from a small helper script.

Example helper script:

```bash
#!/usr/bin/env bash
set -euo pipefail
pkexec /usr/bin/apt-get remove cmatrix
```

Notes:
- `pkexec` shows the system authentication dialog.
- This keeps the privileged action out of Angelique itself.
- If you want to restrict it further with a polkit rule, create a rule in `/etc/polkit-1/rules.d/` that only authorizes your helper path or user.

Example rule template:

```javascript
polkit.addRule(function(action, subject) {
    if (subject.user !== "gwaiffemark") {
        return polkit.Result.NOT_HANDLED;
    }

    if (action.id === "org.freedesktop.policykit.exec") {
        var program = action.lookup("program");
        if (program === "/usr/bin/apt-get") {
            return polkit.Result.YES;
        }
    }

    return polkit.Result.NOT_HANDLED;
});
```

Adjust the path and authorization policy to match your system requirements. A helper script plus `pkexec` is usually the simpler route when you want a GUI prompt.
