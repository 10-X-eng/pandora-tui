# Sensitive data

Personal Pandora credentials belong only in the running player or the desktop
Secret Service keyring. The application has no plaintext credential fallback.
The public partner constants in `device.json` are protocol parameters, not a
listener account.

Do not submit passwords, cookies, tokens, signed stream URLs, raw API responses,
or live-account screenshots in GitHub issues. Music and library metadata can
also identify a listener; use synthetic examples when reporting UI problems.

If a secret is accidentally committed, revoke or rotate it before considering
history cleanup. Removing the latest file alone does not remove older commits.

For suspected credential-disclosure bugs, use GitHub's private vulnerability
reporting feature if enabled on the repository. Avoid posting sensitive details
in public issues.
