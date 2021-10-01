"""
bazel run //finance/reconcile:gnucash_splitwise -- \
  --group_id=<...> \
  --gnucash_book=/wherever/gnucash.gnucash \
  > x.txt

TODO: the note should be associated with a given *split*, not with the whole
transaction. that would support cross-Splitwise-group transactions.
"""

# TODO: support for cross-Splitwise-group transactions in one GnuCash
# transaction

from absl import app
from absl import flags
from absl import logging
import json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import urllib.parse
import re

import math
import xdg
import splitwise
import gnucash

import code
import readline

# Register at: https://secure.splitwise.com/oauth_clients

# ~/.config/gnucash_splitwise_reconciler/...

_CONSUMER_KEY = flags.DEFINE_string("consumer_key", None,
                                    "Splitwise consumer key")
_CONSUMER_SECRET = flags.DEFINE_string("consumer_secret", None,
                                       "Splitwise consumer secret")
# group_id = 22423885
_GROUP_ID = flags.DEFINE_integer("group_id", None, "Splitwise group ID")
_GNUCASH_BOOK = flags.DEFINE_string("gnucash_book", None, "GnuCash file")

# open a GnuCash Book
#book = piecash.open_book("test.gnucash", readonly=True)

# splitwise=\d+  (expense ID)


def print_splitwise_expense(expense, my_user_id):
    net = get_splitwise_net(expense, my_user_id)
    print(
        f"{expense.id} {expense.description} notes={expense.notes} cost={expense.cost} net={net} date={expense.date}"
    )


def retrieve_get_params(port):
    get_params = None

    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal get_params
            query = urllib.parse.urlparse(self.path).query
            get_params = urllib.parse.parse_qs(query)
            logging.info("parsed query string: %s", get_params)

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Auth handled, you can close this tab.")
            self.server.shutdown()

    server = ThreadingHTTPServer(('', port), RequestHandler)
    server.serve_forever()
    return get_params


def assign_token(client, cache_dir):
    token_path = cache_dir / 'splitwise_token.json'
    if token_path.exists():
        with open(token_path) as f:
            access_token = json.load(f)
            logging.info("Access token loaded from %s", access_token)
    else:
        port = 3003
        redirect_uri = f"http://localhost:{port}"
        url, secret = client.getAuthorizeURL()
        print(f"Please go to {url}.")
        params = retrieve_get_params(port=port)
        access_token = client.getAccessToken(params['oauth_token'][0], secret,
                                             params['oauth_verifier'][0])
        logging.info("got access token")

        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, 'w') as f:
            json.dump(access_token, f)
            logging.info("Access token saved to %s", access_token)
    client.setAccessToken(access_token)


def make_client(splitwise_credentials_path):
    if splitwise_credentials_path.exists():
        with open(splitwise_credentials_path) as f:
            splitwise_credentials = json.load(f)
    else:
        splitwise_credentials = {}

    consumer_key = (_CONSUMER_KEY.value
                    or splitwise_credentials['consumer_key'])
    consumer_secret = (_CONSUMER_SECRET.value
                       or splitwise_credentials['consumer_secret'])

    return splitwise.Splitwise(consumer_key, consumer_secret)


def load_expenses():
    config_dir = xdg.xdg_config_home() / 'gnucash_splitwise_reconciler'
    cache_dir = xdg.xdg_cache_home() / 'gnucash_splitwise_reconciler'
    splitwise_credentials_path = config_dir / 'splitwise_credentials.json'

    client = make_client(splitwise_credentials_path)

    assign_token(client, cache_dir)

    my_user_id = client.getCurrentUser().getId()
    # group.name
    expenses = []
    offset = 0
    limit = 100

    while True:
        logging.info("fetching batch of %d items at offset %d", limit, offset)
        batch = client.getExpenses(offset=offset,
                                   limit=limit,
                                   group_id=_GROUP_ID.value)
        # exp.repayments[*].fromUser, .toUser
        # can have: exp.deletedAt
        for expense in batch:
            if expense.getDeletedAt():
                continue
            else:
                expenses.append(expense)
        if len(batch) < limit:
            logging.info("at offset %d, got less than limit %d", offset, limit)
            break
        offset += limit
    logging.info("fetched %d expenses", len(expenses))
    logging.info("useful locals: `client`, `expenses`.")

    #variables = globals().copy()
    #variables.update(locals())
    #shell = code.InteractiveConsole(variables)
    #shell.interact()

    logging.info("done")
    return expenses, my_user_id


def account_from_path(top_account, account_path, original_path=None):
    if original_path == None: original_path = account_path
    account, account_path = account_path[0], account_path[1:]

    account = top_account.lookup_by_name(account)
    if account == None:
        raise Exception("path " + ''.join(original_path) +
                        " could not be found")
    if len(account_path) > 0:
        return account_from_path(account, account_path, original_path)
    else:
        return account


from decimal import Decimal


def gnc_numeric_to_python_Decimal(numeric):
    negative = numeric.negative_p()
    if negative:
        sign = 1
    else:
        sign = 0
    copy = gnucash.GncNumeric(numeric.num(), numeric.denom())
    result = copy.to_decimal(None)
    if not result:
        raise Exception("gnc numeric value %s can't be converted to decimal" %
                        copy.to_string())
    digit_tuple = tuple(int(char) for char in str(copy.num()) if char != '-')
    denominator = copy.denom()
    exponent = int(math.log10(denominator))
    assert ((10**exponent) == denominator)
    return Decimal((sign, digit_tuple, -exponent))


def get_splitwise_net(expense, user_id):
    for exp_user in expense.users:
        if exp_user.id == user_id:
            owed = Decimal(exp_user.getOwedShare())
            paid = Decimal(exp_user.getPaidShare())
            return paid - owed
    raise Exception()


def main(_):
    expenses, my_user_id = load_expenses()

    expenses_by_id = {}
    for expense in expenses:
        expenses_by_id[expense.id] = expense

    # IDs of matched expenses
    splitwise_matched = set()

    session = gnucash.Session(_GNUCASH_BOOK.value)
    try:
        root_account = session.book.get_root_account()
        # TODO: make this a parameter
        account_path = ['Assets', 'Splitwise', 'Under the Roof']
        account_of_interest = account_from_path(root_account, account_path)

        gnucash_unmatched_splits = []

        # TODO: we should actually read the memo on the split, not note on the
        # whole transaction.
        for split in account_of_interest.GetSplitList():
            notes = split.parent.GetNotes()
            if notes:
                match = re.search(r"splitwise=(\d+)", notes)
                if match:
                    splitwise_expense_id = int(match.group(1))
                    splitwise_expense = expenses_by_id[splitwise_expense_id]
                    splitwise_net = get_splitwise_net(splitwise_expense,
                                                      my_user_id)

                    split_amount = gnc_numeric_to_python_Decimal(
                        split.GetAmount())
                    if split_amount != splitwise_net:
                        logging.error(
                            f"Error with Splitwise expense {splitwise_expense_id}: split in GnuCash is {split_amount}, but Splitwise says {splitwise_net}"
                        )
                        raise Exception()
                    assert splitwise_expense_id not in splitwise_matched, f"{splitwise_expense_id} matched to 2 transactions in GnuCash"
                    splitwise_matched.add(splitwise_expense_id)
                    continue

            # transaction is not matched
            gnucash_unmatched_splits.append(split)

            #print("split:", split)
            # split.GetAccount().GetName()
            # >>> t.GetCurrency().get_fullname() --> 'Swiss Franc'

        splitwise_unmatched_ids = set(
            expenses_by_id.keys()) - splitwise_matched
        print()
        print("Unmatched in Splitwise:")

        # Sort by descending net
        def get_abs_net(expense_id):
            expense = expenses_by_id[expense_id]
            return abs(get_splitwise_net(expense, my_user_id))

        for expense_id in sorted(splitwise_unmatched_ids,
                                 key=get_abs_net,
                                 reverse=True):
            expense = expenses_by_id[expense_id]
            print_splitwise_expense(expense, my_user_id)
            #for exp_user in expense.users:
            #    owed = Decimal(exp_user.getOwedShare())
            #    paid = Decimal(exp_user.getPaidShare())
            #    print(
            #        f"  user {exp_user.id}: {paid=} {owed=} {exp_user.getFirstName()} {exp_user.getLastName()}"
            #    )
        print()
        print("Unmatched in GnuCash:")

        # Sort by descending net
        def get_abs_split_net(split):
            return abs(gnc_numeric_to_python_Decimal(split.GetAmount()))

        for split in sorted(gnucash_unmatched_splits,
                            key=get_abs_split_net,
                            reverse=True):
            transaction = split.parent
            notes = transaction.GetNotes()
            print("transaction:", transaction.GetDescription(), transaction,
                  "notes=", notes, "date=", transaction.GetDate())
            split_amount = gnc_numeric_to_python_Decimal(split.GetAmount())
            print("split amount:", split_amount)
            transaction_splits = transaction.GetSplitList()
            print("other splits:")
            for s2 in transaction_splits:
                print("  ", gnc_numeric_to_python_Decimal(s2.GetAmount()),
                      s2.GetAccount().GetName(),
                      s2.GetAccount().GetGUID().to_string())

        #variables = globals().copy()
        #variables.update(locals())
        #shell = code.InteractiveConsole(variables)
        #shell.interact()
    finally:
        session.end()

    pass


if __name__ == '__main__':
    flags.mark_flags_as_required([_GROUP_ID.name, _GNUCASH_BOOK.name])
    app.run(main)
