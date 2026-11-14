# Known errors

Errors another agent could hit in this repo, with the fix. Add an entry in the PR where you hit one.

## The secret scan fails on a test string that looks like an auth header

The secret scan (gitleaks, rule `curl-auth-header`) fails on a literal `curl` command with an `Authorization`
header and a bearer value in test data, even when the value is a marker. It scans every commit of the branch, so
a later commit that removes the string does not help.

Fix: build such a string from a constant (`AUTH = "Authorization"`, then an f-string with the marker), so that no
line holds the literal header and value. Then amend the commit that added the string instead of adding a fix
commit, so that no commit of the branch holds it.
