"""
bazel run //finance/reconcile:gnucash_ubs_account_transactions -- \
  --transactions_csv=/home/agentydragon/downloads/ubs-expenses-account-transactions.csv \
  --gnucash_book=/home/agentydragon/drive/finance/gnucash/gnucash.gnucash

Start of GnuCash is 2021-01-01.

"""

import io
from absl import app
from absl import flags
from absl import logging
import json
import datetime
import urllib.parse
import re
import csv
import math
import decimal

import xdg
import gnucash

from ducktape.finance import gnucash_util

# ~/.config/gnucash_splitwise_reconciler/...

_TRANSACTIONS_CSV = flags.DEFINE_string("transactions_csv", None, "")
_GNUCASH_ACCOUNT_PATH = flags.DEFINE_list(
    "gnucash_account_path", ['Assets', 'UBS', 'Expenses account'],
    "Path to GnuCash account")
_GNUCASH_BOOK = flags.DEFINE_string("gnucash_book", None, "GnuCash file")

# ubs_transaction_id=\d+  (expense ID)


def print_ubs_expense(expense):
    print(expense['id'], expense['trade_date'], expense['amount'],
          expense['description_1'], expense['description_2'],
          expense['description_3'])


_EXPECTED_CSV_COLUMNS = {
    # ?
    'Valuation date',
    # My banking relationship ID (part of IBAN)
    'Banking relationship',
    # Empty.
    'Portfolio',
    # Looks also like part of account's IBAN.
    'Product',
    # Account IBAN (CH...)
    'IBAN',
    # Account currency (CHF)
    'Ccy.',
    # CSV start date - TODO: use this
    'Date from',
    # CSV end date - TODO: use this
    'Date to',
    # Product name ("UBS Personal Account, Credit interest 0%")
    'Description',
    'Trade date',
    'Booking date',
    'Value date',
    'Description 1',
    'Description 2',
    'Description 3',
    'Transaction no.',
    'Exchange rate in the original amount in settlement currency',
    'Individual amount',
    'Debit',
    'Credit',
    'Balance',
}


def load_csv():
    # Returns:
    result = {}
    # encoding='utf-8-sig' skips byte order mark
    with io.open(_TRANSACTIONS_CSV.value, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f, delimiter=';')
        for line in reader:
            assert set(line.keys(
            )) == _EXPECTED_CSV_COLUMNS, f"unexpected keys: {line.keys()}"
            # Lines that don't have 'Debit' or 'Credit' seem to be just
            # transaction details.
            if not (line['Debit'] or line['Credit']):
                continue

            transaction_id = str(line['Transaction no.'])
            assert transaction_id not in result
            assert ((line['Credit'] and not line['Debit'])
                    or (line['Debit'] and not line['Credit']))
            amount = (decimal.Decimal(
                (line['Credit'] or '0').replace('\'', '')) - decimal.Decimal(
                    (line['Debit'] or '0').replace('\'', '')))
            trade_date = datetime.datetime.strptime(line['Trade date'],
                                                    '%d.%m.%Y').date()
            if trade_date < datetime.date(2021, 1, 1):
                # Transaction before start of tracking, pass.
                continue
            result[transaction_id] = {
                'amount': amount,
                'id': transaction_id,
                # TODO: not sure which date to use...
                'trade_date': trade_date,
                'description_1': line['Description 1'],
                'description_2': line['Description 2'],
                'description_3': line['Description 3'],
            }
    return result


def get_split_amount(split):
    return gnucash_util.gnc_numeric_to_python_Decimal(split.GetAmount())


def main(_):
    ubs_transactions_by_ubs_transaction_no = load_csv()

    # IDs of matched expenses
    ubs_matched = set()

    session = gnucash.Session(_GNUCASH_BOOK.value)
    try:
        root_account = session.book.get_root_account()
        # TODO: make this a parameter
        account_path = _GNUCASH_ACCOUNT_PATH.value
        account_of_interest = gnucash_util.account_from_path(
            root_account, account_path)

        gnucash_unmatched_splits = []

        for split in account_of_interest.GetSplitList():
            memo = split.GetMemo()
            match = re.search(r"ubs_transaction_id=([0-9A-Z]+)", memo)

            if match:
                ubs_transaction_id = match.group(1)
                transaction = ubs_transactions_by_ubs_transaction_no[
                    ubs_transaction_id]

                split_amount = gnucash_util.gnc_numeric_to_python_Decimal(
                    split.GetAmount())
                if split_amount != transaction['amount']:
                    logging.error(
                        f"Error with UBS transaction {ubs_transaction_id}: split in GnuCash is {split_amount}, but UBS says {transaction['amount']}"
                    )
                    raise Exception()
                assert ubs_transaction_id not in ubs_matched, f"{ubs_transaction_id} matched to 2 transactions in GnuCash"
                ubs_matched.add(ubs_transaction_id)
                continue

            # transaction is not matched
            gnucash_unmatched_splits.append(split)

            #print("split:", split)
            # split.GetAccount().GetName()
            # >>> t.GetCurrency().get_fullname() --> 'Swiss Franc'

        ubs_unmatched_ids = set(
            ubs_transactions_by_ubs_transaction_no.keys()) - ubs_matched
        print()
        print("Unmatched in UBS:")

        # Sort by descending net
        def get_abs_net(expense_id):
            expense = ubs_transactions_by_ubs_transaction_no[expense_id]
            return abs(expense['amount'])

        for expense_id in sorted(ubs_unmatched_ids,
                                 key=get_abs_net,
                                 reverse=True):
            expense = ubs_transactions_by_ubs_transaction_no[expense_id]
            print_ubs_expense(expense)
        print()
        print("Unmatched in GnuCash:")

        # Sort by descending net
        def get_abs_split_net(split):
            return abs(get_split_amount(split))

        for split in sorted(gnucash_unmatched_splits,
                            key=get_abs_split_net,
                            reverse=True):
            transaction = split.parent
            notes = transaction.GetNotes()
            print("transaction:", transaction.GetDescription(), transaction,
                  "notes=", notes, "date=", transaction.GetDate())
            split_amount = get_split_amount(split)
            print("split amount:", split_amount)
            transaction_splits = transaction.GetSplitList()
            print("other splits:")
            for s2 in transaction_splits:
                print("  ", get_split_amount(s2),
                      s2.GetAccount().GetName(),
                      s2.GetAccount().GetGUID().to_string())
    finally:
        session.end()

    pass


if __name__ == '__main__':
    flags.mark_flags_as_required([
        _TRANSACTIONS_CSV.name, _GNUCASH_ACCOUNT_PATH.name, _GNUCASH_BOOK.name
    ])
    app.run(main)
