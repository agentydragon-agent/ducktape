"""
bazel run //finance/reconcile

To auto-add transactions:

--add_to_gnucash=id1,id2,...
"""

# TODO: check that dates are reasonably close in matched transactions

import datetime
import glob
import yaml
import re

from typing import Dict

from absl import app
from absl import flags
from absl import logging
import xdg
import gnucash

from ducktape.finance import gnucash_util
from ducktape.finance.reconcile import ubs_lib
from ducktape.finance.reconcile import ubs_credit_card_lib
from ducktape.finance.reconcile import splitwise_lib

#variables = globals().copy()
#variables.update(locals())
#shell = code.InteractiveConsole(variables)
#shell.interact()

_ADD_TO_GNUCASH = flags.DEFINE_list('add_to_gnucash', None,
                                    'External IDs to add to GnuCash')


def print_gnucash_split(split):
    transaction = split.parent
    print("transaction:", transaction.GetDate(), transaction.GetDescription(),
          "notes=", transaction.GetNotes())
    for s2 in transaction.GetSplitList():
        heading = "  "
        if s2.GetGUID().to_string() == split.GetGUID().to_string():
            heading = "->"

        print(heading, gnucash_util.get_split_amount(s2),
              s2.GetAccount().GetName())
        # s2.GetAccount().GetGUID().to_string()


# TODO: try to automatch
def match_to_account(external_transaction):
    desc = external_transaction.description.strip().lower()
    if any(
            x in desc for x in {
                'adli markt',
                'bakery'
                'billa',
                'bäcker',
                'coop',
                'denner',
                'ideas felix',
                'migros',
                'tesco',
                'türke',
                # store by Dharmasala
                'dumbo praha',
            }):
        return ['Expenses', 'Groceries']
    elif any(x in desc for x in {
            # Dharmasala
            'amitaya',
            'cafe',
            'cajovna',
            'kavarna',
            'starbucks'
    }):
        return ['Expenses', 'Coffee, tea places']
    elif 'uber' in desc:
        return ['Expenses', 'Uber']
    elif ('sbb easyride' in desc) or ('operator ict' in desc):
        return ['Expenses', 'Public Transportation']
    elif 'aws emea' in desc:
        return ['Expenses', 'Online Services', 'AWS']
    elif ('surcharge abroad' in desc) or ('balance of service prices' in desc):
        return ['Expenses', 'Bank Service Charge', 'CHF']
    else:
        return None


def add_external_to_gnucash(external_transaction, book, account_of_interest,
                            external_id):
    logging.info("Creating transaction for txid %s in GnuCash account %s",
                 external_id, account_of_interest.GetName())

    tx = gnucash.Transaction(book)
    tx.BeginEdit()
    dt = datetime.datetime.combine(external_transaction.trade_date,
                                   datetime.time(0, 0))
    tx.SetDateEnteredSecs(dt)
    tx.SetDatePostedSecs(dt)
    # TODO: tx.SetDatePostedTS(item.date) ?
    currency = book.get_table().lookup('ISO4217', 'CHF')
    tx.SetCurrency(currency)
    tx.SetDescription(external_transaction.description)
    tx.SetNotes(f"Imported at {datetime.datetime.now()}")

    split_in_splitwise = gnucash.Split(book)
    split_in_splitwise.SetParent(tx)
    split_in_splitwise.SetAccount(account_of_interest)
    split_in_splitwise.SetMemo(external_id)

    amount = int(external_transaction.amount * currency.get_fraction())
    print(external_transaction)
    assert amount < 0

    split_in_splitwise.SetValue(
        gnucash.GncNumeric(amount, currency.get_fraction()))
    split_in_splitwise.SetAmount(
        gnucash.GncNumeric(amount, currency.get_fraction()))

    target_path = match_to_account(external_transaction)
    if not target_path:
        desc = external_transaction.description.strip()
        logging.warning("Description unmatched: [%s] - adding to Imbalance",
                        desc)
        target_path = ['Imbalance-CHF']

    imbalance_acct = gnucash_util.account_from_path(book.get_root_account(),
                                                    target_path)
    s2 = gnucash.Split(book)
    s2.SetParent(tx)
    s2.SetAccount(imbalance_acct)
    s2.SetValue(gnucash.GncNumeric(-amount, currency.get_fraction()))
    s2.SetAmount(gnucash.GncNumeric(-amount, currency.get_fraction()))

    tx.CommitEdit()

    logging.info("Added %s", external_id)
    # TODO: once added, remove from txids to add


def main(_):
    config_dir = xdg.xdg_config_home() / 'ducktape'
    cache_dir = xdg.xdg_cache_home() / 'ducktape'

    with open(config_dir / 'config.yaml', 'r') as f:
        config = yaml.safe_load(f)

    with gnucash_util.GnuCashSession(
            config['reconcile']['gnucash_book_path']) as session:
        for reconcile_config in config['reconcile']['mappings']:
            if 'gnucash_account_path' not in reconcile_config:
                raise Exception("no gnucash_account_path")

            gnucash_account_path = reconcile_config['gnucash_account_path']
            print("Reconciling", gnucash_account_path)

            account_of_interest = gnucash_util.account_from_path(
                session.book.get_root_account(), gnucash_account_path)

            if 'ubs_iban' in reconcile_config:
                # TODO: instead of using a single pointer to a single CSV, just
                # load the latest one. Make sure it is for the right IBAN.
                external_transaction_by_external_id = ubs_lib.load_ubs_csv(
                    reconcile_config['csv_path'])

                prefix = 'ubs_transaction_id'
                id_regex = "([0-9A-Z]+)"
            elif 'ubs_cc_account' in reconcile_config:
                external_transaction_by_external_id = {}
                for csv_path in glob.glob(reconcile_config['csv_glob']):
                    # TODO: assert disjoint keys
                    external_transaction_by_external_id.update(
                        ubs_credit_card_lib.load_ubs_credit_card_csv(csv_path))

                prefix = 'ubs_cc_hash'
                id_regex = "([0-9a-zA-Z/+]+)"
            elif 'splitwise_group_id' in reconcile_config:
                external_transaction_by_external_id = splitwise_lib.load_splitwise_expenses(
                    reconcile_config['splitwise_group_id'])

                prefix = 'splitwise'
                id_regex = "([0-9]+)"
            else:
                raise Exception(f"no way to reconcile: {reconcile_config}")

            # 'start_date' sets date at which mapping starts
            if 'start_date' in reconcile_config:
                start_date = datetime.datetime.strptime(
                    reconcile_config['start_date'], '%Y-%m-%d').date()

                external_transaction_by_external_id = {
                    external_id: external_transaction
                    for external_id, external_transaction in
                    external_transaction_by_external_id.items()
                    if external_transaction.trade_date >= start_date
                }

            # External IDs that have been matched.
            matched_external_ids = set()
            gnucash_unmatched_splits = []

            errors = 0
            for split in account_of_interest.GetSplitList():
                transaction_date = split.parent.GetDate().date()
                assert isinstance(transaction_date, datetime.date)
                if transaction_date < start_date:
                    # Skip splits before reconciled date.
                    continue

                memo = split.GetMemo()
                match = re.search(prefix + "=" + id_regex, memo)

                if match:
                    external_id = match.group(1)
                    transaction = external_transaction_by_external_id[
                        external_id]

                    split_amount = gnucash_util.get_split_amount(split)
                    if split_amount != transaction.amount:
                        logging.error(
                            "Error with transaction %s: GnuCash split is %s, "
                            "external system says %s", external_id,
                            split_amount, transaction.amount)
                        errors += 1

                    # TODO: also match the dates
                    days = abs((transaction_date - transaction.trade_date) /
                               datetime.timedelta(days=1))
                    if days >= 2:
                        logging.warning("transaction %s has big delta: %s",
                                        external_id, days)

                    assert external_id not in matched_external_ids, f"{external_id} matched to 2 transactions in GnuCash"
                    matched_external_ids.add(external_id)
                    continue

                # transaction is not matched
                gnucash_unmatched_splits.append(split)

                #print("split:", split)
                # split.GetAccount().GetName()
                # >>> t.GetCurrency().get_fullname() --> 'Swiss Franc'

            if errors > 0:
                raise Exception(f"{errors} errors")

            unmatched_ids = set(external_transaction_by_external_id.keys()
                                ) - matched_external_ids
            print()
            print("Unmatched in external system:")

            # Sort by descending net
            def get_abs_net(expense_id):
                return abs(
                    external_transaction_by_external_id[expense_id].amount)

            for expense_id in sorted(unmatched_ids,
                                     key=get_abs_net,
                                     reverse=True):
                external_id = prefix + "=" + expense_id
                expense = external_transaction_by_external_id[expense_id]
                # print(external_transaction_by_external_id[expense_id])
                automatch = match_to_account(expense)
                marker = (f" (-> {automatch})" if automatch else "")

                print(f"{external_id} {expense.trade_date.isoformat()} "
                      f"{expense.amount} {expense.description}{marker}")
            print()
            print("Unmatched in GnuCash:")

            # Sort by descending net
            def get_abs_split_net(split):
                return abs(gnucash_util.get_split_amount(split))

            for split in sorted(gnucash_unmatched_splits,
                                key=get_abs_split_net,
                                reverse=True):
                print_gnucash_split(split)

                # add those:

            if _ADD_TO_GNUCASH.value:
                for txid in _ADD_TO_GNUCASH.value:
                    if txid not in unmatched_ids:
                        logging.error("not unmatched: %s", txid)
                        continue
                    # TODO: make sure IDs are not done multiple times...
                    external_id = prefix + "=" + txid
                    external_transaction = external_transaction_by_external_id[
                        txid]
                    add_external_to_gnucash(external_transaction, session.book,
                                            account_of_interest, external_id)
        logging.info("Saving the session.")
        session.save()


if __name__ == '__main__':
    app.run(main)
