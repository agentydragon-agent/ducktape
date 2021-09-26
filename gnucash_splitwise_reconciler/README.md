# GnuCash-Splitwise reconciler

Loads expenses from Splitwise and ensures they're matched up to your local
GnuCash book. The matching is done by adding `splitwise=12345` into the notes
field in GnuCash, where `12345` is the Splitwise expense ID.
